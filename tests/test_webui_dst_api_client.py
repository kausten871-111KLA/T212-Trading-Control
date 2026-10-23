import copy
import unittest
from runtime.deepseek.webui_dst_api_client import apply_five_job_plan, form_of
from runtime.deepseek.webui_dst_migration import prepare_dst_plan, PHASE_FOR_NAME
from runtime.deepseek.us_session_dst_audit import uk_target
from datetime import date

NAMES=[
 ("US OPEN — Trading Operations (DEMO)",14,35,"WEEKLY"),
 ("US MIDDAY — Trading Operations (DEMO, monitor+rescan)",17,30,"WEEKLY"),
 ("US CLOSE — Trading Operations (DEMO)",20,35,"WEEKLY"),
 ("Morning Research Runner  (US)- Light DS Trading Operations",13,0,"DAILY"),
 ("US CONTROLLER — decide & authorise",14,0,"WEEKLY"),
]

def rows():
    return [{"id":str(i),"name":name,"is_active":True,"folder_id":None,"meta":None,
             "data":{"prompt":"retain original prompt","model_id":"trading-operations--deepseek",
                     "rrule":f"RRULE:FREQ={freq};BYDAY=MO,TU,WE,TH,FR;BYHOUR={h};BYMINUTE={m}",
                     "terminal":None,"target":None}}
            for i,(name,h,m,freq) in enumerate(NAMES)]

class FakeAPI:
    def __init__(self,items):
        self.data={r["id"]:copy.deepcopy(r) for r in items}
        self.updates=[]
        self.fail_on=None

    def get(self,aid):
        row=copy.deepcopy(self.data[aid])
        phase=PHASE_FOR_NAME[row["name"]]
        monday=uk_target(date(2026,10,26),phase)
        restored=uk_target(date(2026,11,2),phase)
        expected=monday if f"BYHOUR={monday.hour};" in row["data"]["rrule"] else restored
        row["next_runs"]=[int(expected.timestamp()*1_000_000_000)]
        return row

    def update(self,aid,form):
        self.updates.append(aid)
        if aid==self.fail_on:
            self.fail_on=None
            raise RuntimeError("simulated API failure")
        self.data[aid].update(copy.deepcopy(form))
        return self.get(aid)

class WebUIDstAPITests(unittest.TestCase):
    def setUp(self):
        self.initial=rows()
        self.plan=prepare_dst_plan(self.initial)
        self.api=FakeAPI(self.initial)

    def test_round_trip_all_five(self):
        result=apply_five_job_plan(self.api,self.plan)
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["updated_ids"]),5)
        self.assertEqual(apply_five_job_plan(self.api,self.plan,restore=True)["restored"],True)
        self.assertEqual([self.api.data[x["id"]] for x in self.initial],self.initial)

    def test_no_mutation_if_one_model_differs(self):
        self.api.data["2"]["data"]["model_id"]="wrong"
        with self.assertRaises(RuntimeError):
            apply_five_job_plan(self.api,self.plan)
        self.assertEqual(self.api.updates,[])

    def test_rollback_on_partial_failure(self):
        self.api.fail_on="3"
        with self.assertRaises(RuntimeError):
            apply_five_job_plan(self.api,self.plan)
        self.assertEqual([self.api.data[x["id"]] for x in self.initial],self.initial)

    def test_no_mutation_if_rrule_changed(self):
        self.api.data["1"]["data"]["rrule"]="RRULE:FREQ=DAILY;BYHOUR=8;BYMINUTE=0"
        with self.assertRaises(RuntimeError):
            apply_five_job_plan(self.api,self.plan)
        self.assertEqual(self.api.updates,[])

    def test_prompt_and_target_preserved(self):
        self.api.data["0"]["data"]["target"]={"type":"chat"}
        self.api.data["0"]["data"]["prompt"]="sensitive instructions unchanged"
        apply_five_job_plan(self.api,self.plan)
        self.assertEqual(self.api.data["0"]["data"]["prompt"],"sensitive instructions unchanged")
        self.assertEqual(self.api.data["0"]["data"]["target"],{"type":"chat"})

    def test_incomplete_response_rejected(self):
        with self.assertRaises(ValueError):
            form_of({"name":"test"})

    def test_requires_five(self):
        with self.assertRaises(ValueError):
            apply_five_job_plan(self.api,self.plan[:-1])

if __name__=="__main__":
    unittest.main()

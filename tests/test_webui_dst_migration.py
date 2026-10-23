import unittest
from datetime import date
from runtime.deepseek.webui_dst_migration import prepare_dst_plan, PHASE_FOR_NAME

SOURCE = {
 "US OPEN — Trading Operations (DEMO)":("14","35","WEEKLY"),
 "US MIDDAY — Trading Operations (DEMO, monitor+rescan)":("17","30","WEEKLY"),
 "US CLOSE — Trading Operations (DEMO)":("20","35","WEEKLY"),
 "Morning Research Runner  (US)- Light DS Trading Operations":("13","0","DAILY"),
 "US CONTROLLER — decide & authorise":("14","0","WEEKLY"),
}

def fixture():
    return [
        {"id":"id-"+str(i),"name":name,"is_active":True,"data":{
          "model_id":"trading-operations--deepseek",
          "rrule":f"RRULE:FREQ={kind};BYDAY=MO,TU,WE,TH,FR;BYHOUR={hour};BYMINUTE={minute}"
        }} for i,(name,(hour,minute,kind)) in enumerate(SOURCE.items())
    ]


class DstPlanTest(unittest.TestCase):
    def test_five_existing_jobs_only(self):
        plan=prepare_dst_plan(fixture())
        self.assertEqual(len(plan),5)
        self.assertEqual(set(x["name"] for x in plan),set(PHASE_FOR_NAME))

    def test_exact_uk_week_adjustments(self):
        plan={r["name"]:r for r in prepare_dst_plan(fixture())}
        hours={"US OPEN":13,"US MIDDAY":16,"US CLOSE":19,
               "Morning Research Runner":12,"US CONTROLLER":13}
        for name,phase in PHASE_FOR_NAME.items():
            self.assertIn(f"BYHOUR={hours[phase]};",plan[name]["proposed_rrule"])

    def test_preserves_original_restore_manifest(self):
        plan=prepare_dst_plan(fixture())
        for item in plan:
            self.assertNotEqual(item["original_rrule"],item["proposed_rrule"])
            self.assertEqual(item["model_id"],"trading-operations--deepseek")
            self.assertTrue(item["restore_not_before"].startswith("2026-11-01"))

    def test_fails_missing_automation(self):
        with self.assertRaises(ValueError):
            prepare_dst_plan(fixture()[:-1])

    def test_fails_duplicate_automation(self):
        with self.assertRaises(ValueError):
            prepare_dst_plan(fixture()+fixture()[:1])

    def test_fails_other_model(self):
        x=fixture()
        x[0]["data"]["model_id"]="deepseek-v4-pro"
        with self.assertRaises(ValueError):
            prepare_dst_plan(x)

    def test_fails_unexpected_existing_time(self):
        x=fixture()
        x[1]["data"]["rrule"]=x[1]["data"]["rrule"].replace("BYHOUR=17","BYHOUR=16")
        with self.assertRaises(ValueError):
            prepare_dst_plan(x)

    def test_fails_inactive(self):
        x=fixture()
        x[3]["is_active"]=False
        with self.assertRaises(ValueError):
            prepare_dst_plan(x)

    def test_fails_outside_drift_window(self):
        with self.assertRaises(ValueError):
            prepare_dst_plan(fixture(),date(2026,11,2))


if __name__=="__main__":
    unittest.main()

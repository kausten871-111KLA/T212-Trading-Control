"""Disposable real-handler negative and overlap acceptance; no production endpoints."""
import json, os, subprocess, time, unittest, uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from test_persistent_chat_disposable_integration import api, assert_tree

class ResilienceAcceptance(unittest.TestCase):
    def setUp(self):
        self.token=Path(os.environ["WEBUI_IT_TOKEN_FILE"]).read_text().strip()
        baseline=api("/openai/config",token=self.token)
        self.original={k:baseline[k] for k in ["ENABLE_OPENAI_API","OPENAI_API_BASE_URLS","OPENAI_API_KEYS","OPENAI_API_CONFIGS"]}
        self.capture=Path(os.environ["WEBUI_IT_CAPTURE"])
        self.report=Path(os.environ["WEBUI_IT_RESILIENCE"])
        self.control()
        api("/openai/config/update",{"ENABLE_OPENAI_API":True,"OPENAI_API_BASE_URLS":["http://127.0.0.1:38181/v1"],"OPENAI_API_KEYS":["test-only"],"OPENAI_API_CONFIGS":{"0":{"enable":True}}},token=self.token)
        api("/api/models",token=self.token)
    def tearDown(self):
        self.control()
        api("/openai/config/update",self.original,token=self.token)
    def control(self,**value):
        code="import urllib.request,json; r=urllib.request.Request('http://127.0.0.1:38181/control',data="+repr(json.dumps(value).encode())+",headers={'Content-Type':'application/json'});urllib.request.urlopen(r).read()"
        subprocess.run(["docker","exec",os.environ["WEBUI_IT_CONTAINER"],"python","-c",code],check=True,capture_output=True)
    def requests(self):
        return json.loads(self.capture.read_text()) if self.capture.exists() else []
    def record(self,name,data):
        result=json.loads(self.report.read_text()) if self.report.exists() else {}
        result[name]={"at":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),**data}
        self.report.write_text(json.dumps(result,indent=2))
    def fixture(self):
        seed=str(uuid.uuid4())
        chat=api("/api/v1/chats/new",{"chat":{"title":"IT resilience","models":["it-mock"],"history":{"currentId":seed,"messages":{seed:{"id":seed,"role":"assistant","content":"IT_SEED","done":True,"parentId":None,"childrenIds":[]}}},"messages":[]}},token=self.token)
        form={"name":"IT resilience inactive","is_active":False,"data":{"prompt":"Return test marker","model_id":"it-mock","rrule":"DTSTART:20300101T000000\nRRULE:FREQ=DAILY","target":{"type":"chat","chat_id":chat["id"],"context_messages":12}}}
        automation=api("/api/v1/automations/create",form,token=self.token)
        return chat["id"],automation["id"]
    def wait_runs(self,aid,count,timeout=20):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            runs=api("/api/v1/automations/"+aid+"/runs",token=self.token)
            if len(runs)>=count:return runs
            time.sleep(.2)
        self.fail("No completed run records")
    def test_deleted_target_fails_before_provider(self):
        cid,aid=self.fixture()
        before=len(self.requests())
        api("/api/v1/chats/"+cid,method="DELETE",token=self.token)
        api("/api/v1/automations/"+aid+"/run",{},token=self.token)
        runs=self.wait_runs(aid,1);time.sleep(.2)
        observed={"runs":runs,"mock_calls":len(self.requests())-before}
        self.record("deleted_target",observed)
        self.assertEqual(observed["mock_calls"],0)
        self.assertEqual(runs[0]["status"],"error")
    def test_provider_failure_is_not_reported_success(self):
        cid,aid=self.fixture();self.control(fail=True)
        before=len(self.requests())
        api("/api/v1/automations/"+aid+"/run",{},token=self.token)
        runs=self.wait_runs(aid,1);time.sleep(1)
        history=api("/api/v1/chats/"+cid,token=self.token)["chat"]["history"]
        self.record("provider_failure",{"runs":runs,"history":history,"mock_calls":len(self.requests())-before})
        self.assertNotEqual(runs[0]["status"],"success","HTTP 500 provider failure was recorded as automation success")
    def test_overlapping_runs_preserve_history_and_prior_reply_context(self):
        cid,aid=self.fixture();self.control(delay=.8)
        before=len(self.requests())
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(api,"/api/v1/automations/"+aid+"/run",{},token=self.token) for _ in range(2)]
            for f in futures:f.result()
        runs=self.wait_runs(aid,2)
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            history=api("/api/v1/chats/"+cid,token=self.token)["chat"]["history"]
            done=[m for m in history["messages"].values() if m.get("role")=="assistant" and str(m.get("content","")).startswith("IT_RUN_") and m.get("done")]
            if len(done)==2:break
            time.sleep(.2)
        requests=self.requests()[before:]
        first_marker="IT_RUN_"+str(before+1)
        second_has_first=len(requests)==2 and any(m.get("content")==first_marker for m in requests[1]["messages"])
        self.record("overlap",{"runs":runs,"history":history,"requests":requests,"second_has_first_reply":second_has_first})
        assert_tree(self,history)
        self.assertEqual(len(history["messages"]),5)
        self.assertEqual(len(done),2)
        self.assertTrue(second_has_first,"Overlapping run omitted first reply from second-run context; no serialization demonstrated")
    def test_oversized_context_is_bounded_without_truncating_history(self):
        messages={};parent=None
        for n in range(70):
            mid=str(uuid.uuid4())
            messages[mid]={"id":mid,"role":"assistant" if n%2 else "user","content":"IT_LONG_"+str(n)+"_"+"x"*1000,"done":True,"parentId":parent,"childrenIds":[]}
            if parent:messages[parent]["childrenIds"]=[mid]
            parent=mid
        cid=api("/api/v1/chats/new",{"chat":{"title":"IT oversized","models":["it-mock"],"history":{"currentId":parent,"messages":messages},"messages":[]}},token=self.token)["id"]
        aid=api("/api/v1/automations/create",{"name":"IT oversized inactive","is_active":False,"data":{"prompt":"Return test marker","model_id":"it-mock","rrule":"DTSTART:20300101T000000\nRRULE:FREQ=DAILY","target":{"type":"chat","chat_id":cid,"context_messages":999}}},token=self.token)["id"]
        before=len(self.requests())
        api("/api/v1/automations/"+aid+"/run",{},token=self.token)
        self.wait_runs(aid,1)
        request=self.requests()[before]
        prior=request["messages"][:-1]
        history=api("/api/v1/chats/"+cid,token=self.token)["chat"]["history"]
        self.record("oversized_context",{"prior_messages":len(prior),"prior_chars":sum(len(m["content"]) for m in prior),"stored_messages":len(history["messages"])})
        self.assertLessEqual(len(prior),50)
        self.assertLessEqual(sum(len(m["content"]) for m in prior),32000)
        self.assertEqual(len(history["messages"]),72)
        for mid,msg in messages.items():self.assertEqual(history["messages"][mid]["content"],msg["content"])
        assert_tree(self,history)

    def test_timeout_records_error(self):
        cid,aid=self.fixture()
        self.control(delay=40)
        api("/api/v1/automations/"+aid+"/run",{},token=self.token)
        runs=self.wait_runs(aid,1,timeout=40)
        self.record("timeout",{"runs":runs})
        self.assertEqual(runs[0]["status"],"error")
        self.assertIn("timeout",runs[0]["error"])

    def test_manual_chat_keeps_default_db_replay(self):
        cid,aid=self.fixture()
        history=api("/api/v1/chats/"+cid,token=self.token)["chat"]["history"]
        before=len(self.requests())
        uid=str(uuid.uuid4());mid=str(uuid.uuid4())
        api("/api/chat/completions",{"model":"it-mock","stream":True,"messages":[{"role":"user","content":"IT_MANUAL"}],"chat_id":cid,"id":mid,"parent_id":history["currentId"],"user_message":{"id":uid,"parentId":history["currentId"],"role":"user","content":"IT_MANUAL"},"session_id":"it-manual","background_tasks":{}},token=self.token)
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            saved=api("/api/v1/chats/"+cid,token=self.token)["chat"]["history"]["messages"].get(mid,{})
            if saved.get("done"):break
            time.sleep(.2)
        self.assertTrue(saved.get("done"))
        request=self.requests()[before]
        self.assertTrue(any(m.get("content")=="IT_SEED" for m in request["messages"]))
        self.record("manual_default_replay",{"seed_replayed":True,"done":True})

if __name__=="__main__":unittest.main()

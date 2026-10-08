"""Two-run acceptance using the real WebUI automation/completion API.
Requires explicit disposable endpoint, private token file and mock URL.
Never points at production by default. No broker or paid provider calls.
"""
import json, os, time, unittest, uuid
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from urllib.parse import urlparse

BASE=os.environ.get("WEBUI_IT_BASE","http://127.0.0.1:38080")
MOCK=os.environ.get("WEBUI_IT_MOCK","http://127.0.0.1:38181")
def require_loopback(url):
    parsed=urlparse(url)
    if parsed.hostname!="127.0.0.1": raise ValueError("Disposable loopback endpoint required")
require_loopback(BASE);require_loopback(MOCK)
if urlparse(BASE).port not in (38080,38081,38083): raise ValueError("Explicit disposable port 38080/38081/38083 required")

def api(path,data=None,method=None,base=BASE,token=None):
    body=json.dumps(data).encode() if data is not None else None
    headers={"Content-Type":"application/json"}
    if token:headers["Authorization"]="Bearer "+token
    req=Request(base+path,data=body,headers=headers,method=method or ("POST" if data is not None else "GET"))
    with urlopen(req,timeout=20) as r:return json.load(r)

def assert_tree(case,history):
    messages=history["messages"]
    case.assertIn(history["currentId"],messages)
    for mid,msg in messages.items():
        case.assertEqual(mid,msg["id"])
        parent=msg.get("parentId")
        if parent:
            case.assertIn(parent,messages)
            case.assertIn(mid,messages[parent].get("childrenIds",[]))
        children=msg.get("childrenIds",[])
        case.assertEqual(len(children),len(set(children)))
        for child in children:
            case.assertIn(child,messages)
            case.assertEqual(messages[child].get("parentId"),mid)
    current=history["currentId"];seen=set()
    while current:
        case.assertNotIn(current,seen)
        seen.add(current);current=messages[current].get("parentId")

class PersistentChatAcceptance(unittest.TestCase):
    def test_two_runs_real_handler(self):
        token=Path(os.environ["WEBUI_IT_TOKEN_FILE"]).read_text().strip()
        output=Path(os.environ["WEBUI_IT_RECEIPT"])
        receipt={"started_at":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),"status":"RUNNING","checks":{}}
        baseline=api("/openai/config",token=token)
        original={k:baseline[k] for k in ["ENABLE_OPENAI_API","OPENAI_API_BASE_URLS","OPENAI_API_KEYS","OPENAI_API_CONFIGS"]}
        try:
            api("/openai/config/update",{"ENABLE_OPENAI_API":True,"OPENAI_API_BASE_URLS":["http://127.0.0.1:38181/v1"],"OPENAI_API_KEYS":["test-only"],"OPENAI_API_CONFIGS":{"0":{"enable":True}}},token=token)
            models=api("/api/models",token=token)
            self.assertIn("it-mock",[m["id"] for m in models["data"]])
            seed=str(uuid.uuid4())
            chat=api("/api/v1/chats/new",{"chat":{"title":"IT real-handler two-run","models":["it-mock"],"history":{"currentId":seed,"messages":{seed:{"id":seed,"role":"assistant","content":"IT_SEED","done":True,"parentId":None,"childrenIds":[]}}},"messages":[]}},token=token)
            cid=chat["id"];receipt["chat_id"]=cid
            automation=api("/api/v1/automations/create",{"name":"IT real-handler inactive","is_active":False,"data":{"prompt":"Return the next IT marker.","model_id":"it-mock","rrule":"DTSTART:20300101T000000\nRRULE:FREQ=DAILY","target":{"type":"chat","chat_id":cid,"context_messages":12}}},token=token)
            aid=automation["id"];receipt["automation_id"]=aid
            requests_before=len(json.loads(Path(os.environ["WEBUI_IT_CAPTURE"]).read_text())) if Path(os.environ["WEBUI_IT_CAPTURE"]).exists() else 0
            for n in [1,2]:
                api("/api/v1/automations/"+aid+"/run",data={},token=token)
                expected="IT_RUN_"+str(requests_before+n)
                deadline=time.monotonic()+45
                while time.monotonic()<deadline:
                    saved=api("/api/v1/chats/"+cid,token=token)
                    messages=saved["chat"]["history"]["messages"]
                    if any(m.get("content")==expected and m.get("done") is True for m in messages.values()):break
                    time.sleep(.4)
                else:
                    receipt["runs"]=api("/api/v1/automations/"+aid+"/runs",token=token)
                    receipt["history"]=saved["chat"]["history"]
                    self.fail("Timed out awaiting persisted done=true "+expected)
                receipt["checks"]["run_"+str(n)+"_persisted"]=True
            saved=api("/api/v1/chats/"+cid,token=token)
            history=saved["chat"]["history"]
            self.assertEqual(saved["id"],cid)
            self.assertEqual(len(history["messages"]),5)
            self.assertEqual(history["messages"][seed]["content"],"IT_SEED")
            assert_tree(self,history)
            receipt["checks"]["same_chat_and_tree"]=True
            requests=json.loads(Path(os.environ["WEBUI_IT_CAPTURE"]).read_text())
            run2=requests[requests_before+1]
            self.assertTrue(any(m.get("content")=="IT_RUN_"+str(requests_before+1) for m in run2["messages"]))
            self.assertLessEqual(len(run2["messages"]),13)
            self.assertLessEqual(sum(len(m.get("content","")) for m in run2["messages"][:-1]),32000)
            receipt["checks"]["prior_reply_in_bounded_context"]=True
            receipt["checks"]["api_reload"]=True
            receipt["history"]=history
            receipt["requests"]=requests[requests_before:]
            receipt["runs"]=api("/api/v1/automations/"+aid+"/runs",token=token)
            receipt["status"]="PASS_TWO_RUN"
        except Exception as exc:
            receipt["status"]="FAIL"
            receipt["error"]=str(exc)[:2000]
            raise
        finally:
            try:api("/openai/config/update",original,token=token);receipt["config_restored"]=True
            except Exception as exc:receipt["config_restored"]=False;receipt["restore_error"]=str(exc)
            receipt["finished_at"]=time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime())
            output.write_text(json.dumps(receipt,indent=2))

if __name__=="__main__":unittest.main()

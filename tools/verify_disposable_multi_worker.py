"""Real-handler contention across two disposable WebUI containers sharing one SQLite data bind."""
import argparse, json, os, subprocess, sys, time, uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import urlopen

parser=argparse.ArgumentParser();parser.add_argument("--data-dir",required=True)
args=parser.parse_args();data=Path(args.data_dir).resolve()
assert data.name.startswith("webui-handler-integration-")
workers=["open-webui-handler-it-20261008","open-webui-handler-it-worker2-20261008"]
bases=["http://127.0.0.1:38081","http://127.0.0.1:38082"]
for name,base in zip(workers,bases):
 d=json.loads(subprocess.run(["docker","inspect",name],capture_output=True,text=True,check=True).stdout)[0]
 assert any(m["Destination"]=="/app/backend/data" and Path(m["Source"]).resolve()==data for m in d["Mounts"])
 deadline=time.monotonic()+45
 while True:
  try:
   with urlopen(base+"/api/version",timeout=2) as response:json.load(response)
   break
  except Exception:
   if time.monotonic()>deadline:raise
   time.sleep(.5)
os.environ["WEBUI_IT_BASE"]=bases[0]
sys.path.insert(0,str(Path(__file__).parents[1]/"tests"))
from test_persistent_chat_disposable_integration import api,assert_tree
import unittest
case=unittest.TestCase()
script="""import os,sqlite3
from pathlib import Path
from datetime import timedelta
if not os.environ.get('WEBUI_SECRET_KEY'):
 os.environ['WEBUI_SECRET_KEY']=Path('/app/backend/.webui_secret_key').read_text().strip()
from open_webui.utils.auth import create_token
db=sqlite3.connect('file:/app/backend/data/webui.db?mode=ro',uri=True)
assert db.execute('select count(*) from automation where is_active=1').fetchone()[0]==0
uid=db.execute("select id from user where role='admin' order by created_at limit 1").fetchone()[0]
print('IT_TOKEN='+create_token({'id':uid},timedelta(minutes=10)))
"""
r=subprocess.run(["docker","exec",workers[0],"python","-c",script],text=True,capture_output=True,check=True)
token=next(line.split("=",1)[1] for line in r.stdout.splitlines() if line.startswith("IT_TOKEN="))
baseline=api("/openai/config",token=token)
original={k:baseline[k] for k in ["ENABLE_OPENAI_API","OPENAI_API_BASE_URLS","OPENAI_API_KEYS","OPENAI_API_CONFIGS"]}
receipt={"status":"RUNNING","started_at":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime())}
try:
 api("/openai/config/update",{"ENABLE_OPENAI_API":True,"OPENAI_API_BASE_URLS":["http://127.0.0.1:38181/v1"],"OPENAI_API_KEYS":["test-only"],"OPENAI_API_CONFIGS":{"0":{"enable":True}}},token=token)
 for n,(name,base) in enumerate(zip(workers,bases),1):
  control=json.dumps({"prefix":"W"+str(n)+"_RUN_","delay":.8})
  code="import urllib.request; r=urllib.request.Request('http://127.0.0.1:38181/control',data="+repr(control.encode())+",headers={'Content-Type':'application/json'});urllib.request.urlopen(r).read()"
  subprocess.run(["docker","exec",name,"python","-c",code],capture_output=True,check=True)
  case.assertIn("it-mock",[m["id"] for m in api("/api/models",base=base,token=token)["data"]])
 seed=str(uuid.uuid4())
 cid=api("/api/v1/chats/new",{"chat":{"title":"IT multi-worker","models":["it-mock"],"history":{"currentId":seed,"messages":{seed:{"id":seed,"role":"assistant","content":"IT_SEED","done":True,"parentId":None,"childrenIds":[]}}},"messages":[]}},token=token)["id"]
 aid=api("/api/v1/automations/create",{"name":"IT multi-worker inactive","is_active":False,"data":{"prompt":"Return worker marker","model_id":"it-mock","rrule":"DTSTART:20300101T000000\nRRULE:FREQ=DAILY","target":{"type":"chat","chat_id":cid,"context_messages":12}}},token=token)["id"]
 before=[]
 for n in [1,2]:
  p=data/("worker"+str(n)+"-requests.json")
  before.append(len(json.loads(p.read_text())) if p.exists() else 0)
 with ThreadPoolExecutor(max_workers=2) as pool:
  futures=[pool.submit(api,"/api/v1/automations/"+aid+"/run",{},base=base,token=token) for base in bases]
  for f in futures:f.result()
 deadline=time.monotonic()+20
 while time.monotonic()<deadline:
  runs=api("/api/v1/automations/"+aid+"/runs",token=token)
  if len(runs)==2:break
  time.sleep(.2)
 case.assertEqual(len(runs),2);case.assertTrue(all(r["status"]=="success" for r in runs))
 saved=[api("/api/v1/chats/"+cid,base=base,token=token)["chat"]["history"] for base in bases]
 case.assertEqual(saved[0],saved[1]);assert_tree(case,saved[0]);case.assertEqual(len(saved[0]["messages"]),5)
 requests=[json.loads((data/("worker"+str(n)+"-requests.json")).read_text())[before[n-1]] for n in [1,2]]
 first=0 if requests[0]["observed_at_ns"]<requests[1]["observed_at_ns"] else 1
 marker="W"+str(first+1)+"_RUN_"+str(before[first]+1)
 case.assertTrue(any(m.get("content")==marker for m in requests[1-first]["messages"]),"Second worker did not receive first worker reply")
 receipt.update({"status":"PASS","same_chat_two_completed_replies":True,"tree_integrity":True,"both_workers_reload_same_history":True,"second_worker_context_includes_first_reply":True,"run_statuses":[r["status"] for r in runs]})
except Exception as exc:
 receipt.update({"status":"FAIL","error":str(exc)});raise
finally:
 api("/openai/config/update",original,token=token)
 receipt["config_restored"]=True
 receipt["finished_at"]=time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime())
 (data/"multi-worker-acceptance-result.json").write_text(json.dumps(receipt,indent=2))
 print(json.dumps(receipt))

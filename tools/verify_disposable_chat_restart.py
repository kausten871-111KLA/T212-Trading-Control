"""Authenticated restart proof for the isolated handler acceptance container."""
import argparse, json, os, sqlite3, subprocess, time
from pathlib import Path
from urllib.request import Request, urlopen

container="open-webui-handler-it-20261008"
base="http://127.0.0.1:38081"
parser=argparse.ArgumentParser()
parser.add_argument("--data-dir",required=True)
args=parser.parse_args()
data=Path(args.data_dir).resolve()
assert data.name.startswith("webui-handler-integration-")
receipt=json.loads((data/"two-run-acceptance-result.json").read_text())
assert receipt["status"]=="PASS_TWO_RUN"
inspect=json.loads(subprocess.run(["docker","inspect",container],capture_output=True,text=True,check=True).stdout)[0]
assert any(m["Destination"]=="/app/backend/data" and Path(m["Source"])==data for m in inspect["Mounts"])
db=sqlite3.connect(str(data/"webui.db"))
assert db.execute("select count(*) from automation where is_active=1").fetchone()[0]==0
backup=data/"pre-restart-proof.db"
dest=sqlite3.connect(str(backup));db.backup(dest);dest.close()
assert db.execute("pragma integrity_check").fetchone()[0]=="ok"
db.close()
subprocess.run(["docker","restart",container],check=True,capture_output=True)
deadline=time.monotonic()+45
while True:
 try:
  with urlopen(base+"/api/version",timeout=2) as response:version=json.load(response)
  break
 except Exception:
  if time.monotonic()>deadline:raise
  time.sleep(.5)
script="""import os,sqlite3
from pathlib import Path
from datetime import timedelta
if not os.environ.get('WEBUI_SECRET_KEY'):
 os.environ['WEBUI_SECRET_KEY']=Path('/app/backend/.webui_secret_key').read_text().strip()
from open_webui.utils.auth import create_token
db=sqlite3.connect('file:/app/backend/data/webui.db?mode=ro',uri=True)
uid=db.execute("select id from user where role='admin' order by created_at limit 1").fetchone()[0]
print('IT_TOKEN='+create_token({'id':uid},timedelta(minutes=5)))
"""
result=subprocess.run(["docker","exec",container,"python","-c",script],capture_output=True,text=True,check=True)
token=next(line.split("=",1)[1] for line in result.stdout.splitlines() if line.startswith("IT_TOKEN="))
request=Request(base+"/api/v1/chats/"+receipt["chat_id"],headers={"Authorization":"Bearer "+token})
with urlopen(request,timeout=10) as response:saved=json.load(response)
assert saved["chat"]["history"]==receipt["history"],"Persisted chat history changed across restart"
# Verify that the SQLite backup can be restored to a new file and preserves this chat.
restored=data/"restart-proof-restored.db"
src=sqlite3.connect(str(backup));dst=sqlite3.connect(str(restored));src.backup(dst)
assert dst.execute("pragma integrity_check").fetchone()[0]=="ok"
value=dst.execute("select chat from chat where id=?",(receipt["chat_id"],)).fetchone()[0]
assert json.loads(value)["history"]==receipt["history"]
src.close();dst.close()
result={"status":"PASS","at":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),"version":version,"authenticated_history_equal_after_restart":True,"sqlite_backup_restore_integrity":"ok","restored_history_equal":True,"all_automations_inactive":True}
(data/"restart-acceptance-result.json").write_text(json.dumps(result,indent=2))
print(json.dumps(result))

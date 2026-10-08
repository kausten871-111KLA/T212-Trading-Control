"""Run acceptance only against a named disposable WebUI container and matching data bind."""
import argparse, json, os, subprocess, time
from pathlib import Path
from urllib.request import urlopen

parser=argparse.ArgumentParser()
parser.add_argument("--container",default="open-webui-handler-it-20261008")
parser.add_argument("--base",default="http://127.0.0.1:38081")
parser.add_argument("--data-dir",required=True)
parser.add_argument("--pattern",default="test_persistent_chat*integration.py")
parser.add_argument("--match",default=None)
args=parser.parse_args()
if not args.container.startswith("open-webui-handler-it-"):
    raise SystemExit("Explicit handler disposable container required")
if args.base not in ("http://127.0.0.1:38081","http://127.0.0.1:38083"):
    raise SystemExit("Explicit candidate loopback endpoint required")
data=Path(args.data_dir).resolve()
if not data.name.startswith("webui-handler-integration-"):
    raise SystemExit("Explicit handler disposable data directory required")
inspect=json.loads(subprocess.run(["docker","inspect",args.container],capture_output=True,text=True,check=True).stdout)[0]
binds=[m for m in inspect["Mounts"] if m["Destination"]=="/app/backend/data"]
if len(binds)!=1 or Path(binds[0]["Source"]).resolve()!=data:
    raise SystemExit("Container data bind does not match disposable directory")
deadline=time.monotonic()+45
while True:
    try:
        with urlopen(args.base+"/api/version",timeout=2) as response:
            version=json.load(response)
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
assert db.execute('select count(*) from automation where is_active=1').fetchone()[0]==0
uid=db.execute("select id from user where role='admin' order by created_at limit 1").fetchone()[0]
print('IT_TOKEN='+create_token({'id':uid},timedelta(minutes=20)))
"""
result=subprocess.run(["docker","exec",args.container,"python","-c",script],capture_output=True,text=True,check=True)
token=next(line.split("=",1)[1] for line in result.stdout.splitlines() if line.startswith("IT_TOKEN="))
path=data/".handler-it-token"
path.write_text(token);path.chmod(0o600)
env=os.environ.copy()
env.update({"WEBUI_IT_BASE":args.base,"WEBUI_IT_CONTAINER":args.container,"WEBUI_IT_TOKEN_FILE":str(path),"WEBUI_IT_CAPTURE":str(data/"handler-mock-requests.json"),"WEBUI_IT_RECEIPT":str(data/"two-run-acceptance-result.json"),"WEBUI_IT_RESILIENCE":str(data/"resilience-acceptance-result.json")})
try:
    command=["python3","-m","unittest","discover","-s","tests","-p",args.pattern,"-v"]
    if args.match:command+=["-k",args.match]
    result=subprocess.run(command,env=env)
finally:
    path.unlink(missing_ok=True)
raise SystemExit(result.returncode)

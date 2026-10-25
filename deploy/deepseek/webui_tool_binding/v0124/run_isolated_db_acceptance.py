#!/usr/bin/env python3
"""Safely test the v0.12.4 custom WebUI image on an isolated COPY of Oct 25 backup.

Staging only. Never changes production Compose, image, volumes, services, orders
or original backup. Does not launch WebUI or its automation scheduler, and both
Docker tasks have --network none. The only SQLite migrations affect the copy.
"""
from pathlib import Path
import hashlib
import os
import secrets
import shutil
import sqlite3
import subprocess
import sys

IMAGE = "local/open-webui-toolbinding-v0124-stage:20261025"
OLD_IMAGE = "local/open-webui-toolbinding-v0123-stage:20261020"
OLD_ID = "sha256:7d8d04ead2b7c38d99b12b80a777b6030f3c694c491ca93e6bb010b5c3e82483"
BASE = Path("/home/katie/webui-v0124-stage-20261025")
BACKUP = Path("/home/katie/backups/webui-v0124-security-20261025")
DATA = BASE / "data-test-retry-4"  # Retain all previous stage attempts

CHECK = r'''
import asyncio, datetime, json, os, sqlite3, sys, types
from fastapi import FastAPI, Request
from open_webui.models.models import Models
from open_webui.models.users import Users
from open_webui.utils.automations import _resolve_model_defaults
from open_webui.utils.automation_tool_contract import assess_automation_tools
from open_webui.utils.tools import get_tools
MODEL="trading-operations--deepseek"
EXPECTED_TOOLS={
    "trading_212_demo_gateway_tool",
    "market_data_gateway",
    "contabo_command_bridge",
    "trading_brain_research_context",
    "twelve_data_global_research",
}
# Monday 26 Oct while UK is on GMT, US still on daylight-saving time.
EXPECTED_JOBS={
    "Morning Research Runner":(12,0),
    "US CONTROLLER":(13,0),
    "US OPEN":(13,35),
    "US MIDDAY":(16,30),
    "US CLOSE":(19,35),
}
async def verify():
    db=sqlite3.connect("file:/app/backend/data/webui.db?mode=ro",uri=True)
    try:
        assert db.execute("pragma integrity_check").fetchone()[0]=="ok","Stage DB integrity failed"
        rows=db.execute("select name,is_active,data,next_run_at from automation").fetchall()
        jobs=[(name,active,json.loads(data),nxt) for name,active,data,nxt in rows
              if json.loads(data).get("model_id")==MODEL]
        assert len(jobs)==5,f"Expected exactly five owner-model automations, found {len(jobs)}"
        for prefix,clock in EXPECTED_JOBS.items():
            matches=[j for j in jobs if j[0].startswith(prefix)]
            assert len(matches)==1,f"Expected one automation named {prefix}; found {len(matches)}"
            name,active,data,next_ns=matches[0]
            assert active,f"{prefix} inactive"
            assert data.get("prompt") and data.get("rrule"),f"{prefix} lost prompt/rrule"
            assert next_ns,f"{prefix} no next_run_at"
            dt=datetime.datetime.fromtimestamp(next_ns/1_000_000_000,datetime.timezone.utc)
            assert (dt.year,dt.month,dt.day,dt.hour,dt.minute)==(2026,10,26,*clock),(
                 f"{prefix} next UTC run mismatch: {dt.isoformat()} expected Mon 26 Oct {clock}")
            print("STAGED_AUTOMATION_PASS",prefix,dt.isoformat(),flush=True)
        m=db.execute("select meta from model where id=?",(MODEL,)).fetchone()
        assert m,"Existing DeepSeek trading model missing"
        tool_ids=list(json.loads(m[0]).get("toolIds",[]))
        assert set(tool_ids)==EXPECTED_TOOLS,(
            f"Expected exactly five model tool IDs; got {len(tool_ids)} "
            f"missing={sorted(EXPECTED_TOOLS-set(tool_ids))} extra={sorted(set(tool_ids)-EXPECTED_TOOLS)}")
        for tool_id in EXPECTED_TOOLS:
            assert db.execute("select 1 from tool where id=?",(tool_id,)).fetchone(),(
                 f"Tool {tool_id} missing from database")
    finally:
        db.close()
    model=await Models.get_model_by_id(MODEL)
    assert model,"WebUI model API does not resolve existing owner"
    user=Users.get_user_by_id(model.user_id)
    if asyncio.iscoroutine(user):
        user=await user
    assert user,"WebUI model user absent"
    app=types.SimpleNamespace(state=types.SimpleNamespace(MODELS={MODEL:{"info":{"meta":{}}}}))
    defaults=await _resolve_model_defaults(app,MODEL)
    assert set(defaults.get("tool_ids",[]))==EXPECTED_TOOLS,(
        "Scheduled-run default resolution lost one or more existing tools")
    req=Request({"type":"http","app":FastAPI(),"headers":[]})
    params={"__user__":{"id":user.id,"name":user.name,"email":user.email,"role":user.role},
            "__model__":{"id":MODEL},"__messages__":[],"__files__":[]}
    got=await get_tools(req,tool_ids,user,params)
    resolved={item.get("tool_id") for item in got.values()}
    assert EXPECTED_TOOLS<=resolved,(
        "Tool schema unresolved: "+str(sorted(EXPECTED_TOOLS-resolved)))
    receipt=assess_automation_tools(tool_ids,tool_ids,got)
    assert receipt.ready and not receipt.missing_ids,"Tool contract fails for scheduled automation"
    print("V0124_ISOLATED_DB_PASS","automations",len(jobs),
          "bound_tools",len(tool_ids),"resolved_functions",len(got),
          "python",sys.version.split()[0],
          "provider_calls",0,"broker_orders",0,flush=True)
asyncio.run(verify())
'''

def run(args, *, stdin=None, env=None):
    print("STAGE_STEP", args[:3], flush=True)
    subprocess.run(args, input=stdin, text=stdin is not None, env=env, check=True)

def out(args):
    return subprocess.check_output(args,text=True).strip()

COPY_SNAPSHOT = r'''
# Runs as root inside a DISPOSABLE, network-disabled container.
# /source is the already completed Oct 25 backup mounted read-only.
# /dest is a NEW, empty staging directory; production volume is NOT mounted.
from pathlib import Path
import hashlib, os, shutil, sqlite3
src=Path("/source")
dst=Path("/dest")
assert src.is_dir() and dst.is_dir(), "Stage source/destination unavailable"
assert not list(dst.iterdir()), "Refusing to overwrite an existing stage"
source_db=src/"webui.db"
assert source_db.is_file(), "Archived SQLite file missing"

def db_integrity(p):
    with sqlite3.connect(p.as_uri()+"?mode=ro&immutable=1",uri=True,timeout=20) as db:
        assert db.execute("pragma integrity_check").fetchone()[0]=="ok", "Archived SQLite integrity failure"
        tables=db.execute("select count(*) from sqlite_master where type='table'").fetchone()[0]
        assert tables>=48, f"Unexpected schema with {tables} tables"
    return tables

def sha(p):
    h=hashlib.sha256()
    with p.open("rb") as stream:
        for chunk in iter(lambda: stream.read(2*1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()

tables=db_integrity(source_db)
root=src.resolve(strict=True)
for folder,dirs,files in os.walk(src,followlinks=False):
    here=Path(folder)
    for name in dirs:
        assert not (here/name).is_symlink(), "Symlinked archive directory"
    for name in files:
        p=here/name
        if p.is_symlink():
            assert not os.path.isabs(os.readlink(p)), "Absolute archive symlink"
            target=p.resolve(strict=True)
            assert target.is_relative_to(root) and target.is_file(), "Archive symlink escape"
# Copy the already-consistent backup as bytes, NOT a second sqlite3.backup.
shutil.copytree(src,dst,dirs_exist_ok=True,symlinks=True,copy_function=shutil.copy2)
copied=dst/"webui.db"
assert sha(source_db)==sha(copied), "Copied SQLite hash differs from preserved backup"
assert db_integrity(copied)==tables, "Copied SQLite schema changed"
print("V0124_BACKUP_COPY_PASS", "tables",tables,"db_bytes",copied.stat().st_size,
      "backup_preserved",True,flush=True)
'''

def copy_verified_snapshot():
    # Source DB is mode 0600 root:root, inaccessible to the unprivileged
    # host account. Do not chmod/chown or relax access to the protected backup.
    # Run a non-networked helper with the source mounted read-only instead.
    assert not DATA.exists(), "Retry stage already exists; do not overwrite it"
    DATA.mkdir(mode=0o700)
    run(["docker","run","--rm","-i","--network","none",
         "--security-opt","no-new-privileges",
         "--cpus","2","--memory","2g",
         "-v",f"{BACKUP/'data'}:/source:ro",
         "-v",f"{DATA}:/dest",
         "--entrypoint","python",OLD_IMAGE,"-"],stdin=COPY_SNAPSHOT)

def main():
    assert out(["docker","inspect","-f","{{.Image}}","open-webui"])==OLD_ID, (
        "Running production image changed; no staging changes")
    assert out(["docker","inspect","-f","{{.State.Health.Status}}","open-webui"])=="healthy", (
        "Live WebUI unhealthy; stop")
    assert (BACKUP/"data"/"webui.db").is_file(),"Oct 25 backup missing"
    assert (BACKUP/"docker-compose.yml").is_file(),"Oct 25 original Compose backup missing"
    assert BASE.is_dir(),"Oct 25 candidate source stage missing"
    assert not DATA.exists(),"Retry stage already exists; inspect before rerunning"
    assert out(["docker","image","inspect","-f","{{.Id}}",IMAGE]),"Candidate image missing"
    copy_verified_snapshot()
    env=dict(os.environ)
    env["WEBUI_SECRET_KEY"]=secrets.token_hex(32) # disposable, never logged
    env["PYTHONDONTWRITEBYTECODE"]="1"
    run(["docker","run","--rm","-i","--network","none","--read-only",
         "--tmpfs","/tmp:rw,nosuid,size=128m",
         "--security-opt","no-new-privileges",
         # Root needs default DAC to traverse 0700 stage and read 0600 copied DB.
         # Container has --network none and no production mounts or credentials.
         "--cpus","2","--memory","3g",
         "-v",f"{DATA}:/app/backend/data",
         "-e","WEBUI_SECRET_KEY","-e","PYTHONDONTWRITEBYTECODE",
         "-e","ENABLE_OLLAMA_API=false","-e","ENABLE_OPENAI_API=false",
         "--entrypoint","python",IMAGE,"-"],stdin=CHECK,env=env)
    assert out(["docker","inspect","-f","{{.Image}}","open-webui"])==OLD_ID
    print("PRODUCTION_UNCHANGED","staged_data_only",flush=True)

if __name__=="__main__":
    os.umask(0o077)
    try:
        main()
    except Exception as exc:
        print("V0124_ISOLATED_DB_BLOCKED",type(exc).__name__,str(exc)[:800],flush=True)
        sys.exit(1)

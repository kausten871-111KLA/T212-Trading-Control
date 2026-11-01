"""Supervised additive WebUI Trading Brain deployment.

Run inside the *existing* Open WebUI container with the server-side configured
OPENWEBUI_ADMIN_API_KEY. No broker APIs, orders, model inference or schedules.
Stages are explicit, API-backed and reversible. Never prints credentials.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
import urllib.parse
import urllib.error
import urllib.request

BASE="http://localhost:8080"
MODEL_ID="trading-operations--deepseek"
TOOL_ID="trading_brain_research_context"
TOOL_NAME="Trading Brain Research Context"
BASE_TOOLS=[
    "trading_212_demo_gateway_tool",
    "market_data_gateway",
    "contabo_command_bridge",
]
BUNDLE=Path("/tmp/trading_brain_webui_bundle.py")
MANIFEST=Path("/tmp/tradingbrain_predeploy_manifest.json")
SQLITE_DB=Path("/app/backend/data/webui.db")
PROMPT_MARKER="TRADING BRAIN RESEARCH CONTEXT (ADDITIVE)"
PROMPT_TEXT=(
  "\n\n"+PROMPT_MARKER+"\n"
  "Use the trading_brain_research function when genuine Alpaca market-data "
  "snapshots or dated bars can materially improve candidate evaluation. "
  "Pass actual gateway JSON, accurate as-of time, and a historical comparable "
  "volume baseline only if available. Examine price momentum, quote economics, "
  "point-in-time research history and evidence-quality annotations. "
  "Treat hypotheses, missing values and spread costs as decision information, "
  "not categorical bans, trade limits or automatic vetoes. Scenario quantity is "
  "for cost comparison, NOT order sizing. Preserve your existing principles "
  "and fully autonomous Trading 212 DEMO research, buy, sell and monitoring "
  "through the original gateway, schedules and persistent controller. "
  "LIVE remains disabled. Do not fabricate catalysts, RVOL, quotes or outcomes. "
  "Do not substitute this research tool for the existing broker tool.\n"
)

def api(method,path,payload=None):
    key=os.getenv("OPENWEBUI_ADMIN_API_KEY","").strip()
    if not key:
        raise RuntimeError("Admin API key missing inside WebUI environment")
    if not path.startswith("/api/v1/"):
        raise ValueError("Unexpected API path")
    body=json.dumps(payload,ensure_ascii=False).encode() if payload is not None else None
    req=urllib.request.Request(
        BASE+path,
        data=body,method=method.upper(),
        headers={
            "Authorization":"Bearer "+key,
            "Accept":"application/json",
            **({"Content-Type":"application/json"} if body is not None else {}),
        },
    )
    try:
        with urllib.request.urlopen(req,timeout=35) as resp:
            raw=resp.read()
            return json.loads(raw.decode()) if raw else None
    except urllib.error.HTTPError as err:
        # Do not print response bodies: the server could echo sensitive content.
        raise RuntimeError("WebUI API HTTP "+str(err.code)+" during "+method+" "+path.split("?")[0]) from None


def read_model():
    return api("GET","/api/v1/models/model?"+urllib.parse.urlencode({"id":MODEL_ID}))

def read_tool(id):
    try:
        return api("GET","/api/v1/tools/id/"+id)
    except RuntimeError as e:
        if "HTTP 404" in str(e):
            return None
        raise

def state():
    db=sqlite3.connect("file:"+str(SQLITE_DB)+"?mode=ro",uri=True,timeout=10)
    db.row_factory=sqlite3.Row
    autos=[dict(r) for r in db.execute(
        "SELECT id,name,is_active,data,created_at,next_run_at,last_run_at "
        "FROM automation ORDER BY id"
    )]
    tool_ids=[r["id"] for r in db.execute("SELECT id FROM tool ORDER BY id")]
    db.close()
    return {"automations":autos,"tool_ids":tool_ids}


def _automation_digest(autos):
    # Last run and next run timestamps can legitimately progress; IDs,
    # names, enabled flags and schedule/user prompts may not change here.
    stable=[]
    for row in autos:
        stable.append({
            "id":row["id"],"name":row["name"],
            "is_active":row["is_active"],"created_at":row["created_at"],
            "data":row["data"],
        })
    return hashlib.sha256(json.dumps(stable,sort_keys=True,default=str).encode()).hexdigest()


def assert_original(model,mode):
    if not model or model.get("id")!=MODEL_ID:
        raise RuntimeError("Target trading model missing")
    meta=model.get("meta") or {}
    original=meta.get("toolIds",[])
    if mode=="before" and original!=BASE_TOOLS:
        raise RuntimeError("Current tool list changed: stop and review rather than overwrite")
    if mode=="after" and original!=BASE_TOOLS+[TOOL_ID]:
        raise RuntimeError("Model's existing three tools were not preserved")
    if model.get("base_model_id")!="deepseek-v4-pro":
        raise RuntimeError("Unexpected underlying model changed")
    return original


def stage_manifest():
    if MANIFEST.exists():
        existing=json.loads(MANIFEST.read_text())
        if existing.get("model",{}).get("id")!=MODEL_ID:
            raise RuntimeError("Existing rollback manifest belongs to another model")
        print("PREFLIGHT_REUSED_EXISTING_MANIFEST")
        return existing
    data=state()
    model=read_model()
    assert_original(model,"before")
    if TOOL_ID in data["tool_ids"] or read_tool(TOOL_ID):
        raise RuntimeError("Tool already exists before snapshot; do not overwrite")
    if len(data["automations"])!=4:
        raise RuntimeError("Expected four existing automations, found "+str(len(data["automations"])))
    if not all(a["is_active"] for a in data["automations"]):
        raise RuntimeError("One or more existing automations inactive before deployment")
    if not BUNDLE.is_file():
        raise RuntimeError("Staged standalone tool source not present")
    source=BUNDLE.read_text(encoding="utf-8")
    if len(source)<10000 or len(source)>110000:
        raise RuntimeError("Unexpected tool source length")
    if source.count("class Tools:")!=1:
        raise RuntimeError("Tool class missing")
    compile(source,str(BUNDLE),"exec")
    backup={
      "model":{k:model[k] for k in (
          "id","name","base_model_id","params","meta","is_active",
          "access_grants","version_id") if k in model},
      "automation_digest":_automation_digest(data["automations"]),
      "automation_ids":sorted(a["id"] for a in data["automations"]),
      "tool_ids_before":data["tool_ids"],
      "bundle_sha256":hashlib.sha256(source.encode()).hexdigest(),
      "captured_at_epoch":int(time.time()),
    }
    fd=os.open(str(MANIFEST),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,"w") as f:
        json.dump(backup,f,ensure_ascii=False,indent=2)
    print("PREFLIGHT_PASS","model",MODEL_ID,
          "existing_attached_tools",len(BASE_TOOLS),
          "automations",len(data["automations"]),
          "bundle_bytes",len(source.encode()),
          "rollback_manifest",str(MANIFEST))
    return backup


def check_schedule(manifest):
    now=state()
    if _automation_digest(now["automations"])!=manifest["automation_digest"]:
        raise RuntimeError("Automation objects changed since preflight: stop immediately")
    return now


def register():
    manifest=stage_manifest()
    check_schedule(manifest)
    m=read_model()
    assert_original(m,"before")
    if read_tool(TOOL_ID):
        raise RuntimeError("Tool already exists; refusing to replace")
    content=BUNDLE.read_text(encoding="utf-8")
    if hashlib.sha256(content.encode()).hexdigest()!=manifest["bundle_sha256"]:
        raise RuntimeError("Bundle changed after snapshot")
    payload={
        "id":TOOL_ID,"name":TOOL_NAME,"content":content,
        "meta":{"description":"Additive, broker-neutral research context. Does not submit orders."},
        "commit_message":"Register tested standalone Trading Brain evidence research tool",
    }
    created=api("POST","/api/v1/tools/create",payload)
    if not created or created.get("id")!=TOOL_ID:
        raise RuntimeError("Tool creation response unexpected")
    tool=read_tool(TOOL_ID)
    methods=[x.get("name") for x in tool.get("specs",[])]
    if methods!=["trading_brain_research"]:
        raise RuntimeError("Registered tool specs unexpected: "+repr(methods))
    if tool.get("content")!=content:
        raise RuntimeError("Registered tool source differs from tested bundle")
    check_schedule(manifest)
    assert_original(read_model(),"before")
    print("REGISTER_PASS",TOOL_ID,"methods",methods,"source_sha256",manifest["bundle_sha256"])


def model_form(model,new_meta,new_params):
    # Deliberately omit access_grants: WebUI preserves stored grants for an
    # unchanged owner when the form field is absent.
    return {
        "id":MODEL_ID,"name":model["name"],
        "base_model_id":model["base_model_id"],
        "meta":new_meta,"params":new_params,
        "is_active":model["is_active"],
        "commit_message":"Add Trading Brain research tool and preserve existing DEMO tool bindings",
    }


def bind():
    manifest=stage_manifest()
    check_schedule(manifest)
    tool=read_tool(TOOL_ID)
    if not tool:
        raise RuntimeError("Register the tool before binding")
    methods=[x.get("name") for x in tool.get("specs",[])]
    if methods!=["trading_brain_research"]:
        raise RuntimeError("Registered method changed")
    model=read_model()
    assert_original(model,"before")
    old=manifest["model"]
    for key in ("params","meta","name","base_model_id","is_active"):
        if model.get(key)!=old.get(key):
            raise RuntimeError("Trading model changed after snapshot, abort binding")
    meta=deepcopy(model["meta"])
    params=deepcopy(model["params"])
    if PROMPT_MARKER in str(params.get("system","")):
        raise RuntimeError("Prompt already updated unexpectedly")
    meta["toolIds"]=BASE_TOOLS+[TOOL_ID]
    params["system"]=params.get("system","")+PROMPT_TEXT
    result=api("POST","/api/v1/models/model/update",
               model_form(model,meta,params))
    if not result or result.get("id")!=MODEL_ID:
        raise RuntimeError("Model update response invalid")
    verify()
    print("MODEL_BIND_PASS","model",MODEL_ID,
          "tool_count",len(meta["toolIds"]),
          "prompt_appended_chars",len(PROMPT_TEXT))


def verify():
    manifest=json.loads(MANIFEST.read_text())
    now=check_schedule(manifest)
    model=read_model()
    assert_original(model,"after")
    old=manifest["model"]
    if model["meta"].get("skillIds")!=old["meta"].get("skillIds"):
        raise RuntimeError("Original skills were changed")
    if model["meta"].get("knowledge")!=old["meta"].get("knowledge"):
        raise RuntimeError("Original knowledge changed")
    if model["base_model_id"]!=old["base_model_id"]:
        raise RuntimeError("Base model altered")
    if model["is_active"]!=old["is_active"]:
        raise RuntimeError("Model active setting altered")
    orig_sys=old["params"].get("system","")
    new_sys=model["params"].get("system","")
    if new_sys!=orig_sys+PROMPT_TEXT:
        raise RuntimeError("Prompt does not match exact additive change")
    if {k:v for k,v in model["params"].items() if k!="system"} != {
       k:v for k,v in old["params"].items() if k!="system"}:
        raise RuntimeError("Model non-system parameters changed")
    for k in old["meta"]:
        if k!="toolIds" and model["meta"].get(k)!=old["meta"].get(k):
            raise RuntimeError("Unexpected model meta change: "+k)
    t=read_tool(TOOL_ID)
    if t is None or [x.get("name") for x in t["specs"]] != ["trading_brain_research"]:
        raise RuntimeError("Research tool missing")
    if len(now["automations"])!=4 or not all(a["is_active"] for a in now["automations"]):
        raise RuntimeError("Automation loss")
    print("VERIFY_PASS","attached_tool_ids",model["meta"]["toolIds"],
          "automations",len(now["automations"]),
          "skill_ids_preserved",len(model["meta"].get("skillIds") or []),
          "knowledge_preserved",len(model["meta"].get("knowledge") or []),
          "original_prompt_preserved",True,
          "research_method",t["specs"][0]["name"])


def rollback():
    manifest=json.loads(MANIFEST.read_text())
    model=read_model()
    current=model.get("meta",{}).get("toolIds")
    if current not in (BASE_TOOLS,BASE_TOOLS+[TOOL_ID]):
        raise RuntimeError("Other user changes detected; manual rollback required")
    old=manifest["model"]
    if current==BASE_TOOLS+[TOOL_ID]:
        api("POST","/api/v1/models/model/update",
            model_form(model,old["meta"],old["params"]))
    model=read_model()
    assert_original(model,"before")
    if read_tool(TOOL_ID):
        response=api("DELETE","/api/v1/tools/id/"+TOOL_ID+"/delete")
        if response is not True:
            raise RuntimeError("Tool delete request did not confirm success")
    model=read_model()
    assert_original(model,"before")
    check_schedule(manifest)
    print("ROLLBACK_PASS","tool_removed",read_tool(TOOL_ID) is None,
          "original_attached_tools",model["meta"]["toolIds"])


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("phase",choices=["preflight","register","bind","verify","rollback"])
    args=p.parse_args()
    if args.phase=="preflight":stage_manifest()
    elif args.phase=="register":register()
    elif args.phase=="bind":bind()
    elif args.phase=="verify":verify()
    elif args.phase=="rollback":rollback()

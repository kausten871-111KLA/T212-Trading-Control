"""Additive, rollback-capable Twelve Data WebUI tool deployment.

Run INSIDE running WebUI container. Does NOT contact a model or broker.
Uses the existing administrator API script, not direct database mutation.
"""
from __future__ import annotations
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, "/tmp")
from deploy_trading_brain_webui import (
    api, read_model, read_tool, model_form,
    state, _automation_digest,
)

MODEL="trading-operations--deepseek"
NEW_TOOL="twelve_data_global_research"
OLD_IDS=[
    "trading_212_demo_gateway_tool",
    "market_data_gateway",
    "contabo_command_bridge",
    "trading_brain_research_context",
]
CODE=Path("/tmp/twelve_data_webui_tool.py")
BACKUP=Path("/tmp/twelve_data_deploy_manifest.json")
MARKER="\n\nTWELVE DATA GLOBAL MARKET RESEARCH (ADDITIVE)\n"
PROMPT=(
    MARKER+
    "You have an additional Twelve Data research tool (twelve_data_research) "
    "through the existing authenticated Contabo bridge. Use symbol_search to "
    "identify exact market/MIC/currency, quote for source prices where permitted, "
    "time_series for supported dated OHLCV history, api_usage when budget context "
    "is needed. Preserve currency units (UK GBp is not GBP), exchange-local daily "
    "dates, intraday UTC and provider plan or delayed-data restrictions. "
    "Use original Alpaca and T212 DEMO gateway for US execution and verified "
    "trade receipts. Treat Twelve Data as market research ONLY, never a broker "
    "quote, guaranteed real-time feed or order-execution connection. "
    "You may pass compatible quote/intraday output to Trading Brain only after "
    "its deployed normalizer supports Twelve Data. Keep original autonomous DEMO "
    "rules and all existing OPEN/MIDDAY/CLOSE schedules; LIVE stays disabled. "
    "Do not invent absent VWAP, RVOL, catalysts, fees, fills or currency conversion.\n"
)

def source():
    code=CODE.read_text(encoding="utf-8")
    compile(code, str(CODE), "exec")
    if not 1000<len(code)<20000 or "class Tools:" not in code:
        raise RuntimeError("Unexpected candidate tool source")
    for bad in ("place_market_order", "import subprocess", "TRADING212_API_KEY"):
        if bad in code:
            raise RuntimeError("Unsupported command in tool source")
    return code

def model():
    m=read_model()
    if not m or m.get("id")!=MODEL:
        raise RuntimeError("Model not found")
    return m

def autos():
    v=state()["automations"]
    if len(v)!=4 or not all(x["is_active"] for x in v):
        raise RuntimeError("Original four active schedules not verified")
    return _automation_digest(v)

def preflight():
    m=model()
    if m["meta"].get("toolIds")!=OLD_IDS:
        raise RuntimeError("Four original tool bindings differ; don't overwrite")
    if m["base_model_id"]!="deepseek-v4-pro":
        raise RuntimeError("Unexpected underlying model")
    if read_tool(NEW_TOOL) is not None:
        raise RuntimeError("Tool already exists before backup")
    src=source()
    digest=autos()
    backup={
        "id":m["id"], "name":m["name"],
        "base_model_id":m["base_model_id"],
        "params":m["params"],"meta":m["meta"],
        "is_active":m["is_active"],
        "autos_sha256":digest,
        "tool_source_sha256":hashlib.sha256(src.encode()).hexdigest(),
    }
    if BACKUP.exists():
        if json.loads(BACKUP.read_text())!=backup:
            raise RuntimeError("Existing Twelve rollback snapshot is different")
    else:
        fd=os.open(BACKUP,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,"w") as f:json.dump(backup,f,indent=2)
    print("TWELVE_PREFLIGHT_PASS","prior_tool_count",len(OLD_IDS),
          "automations",4,"source_sha256",backup["tool_source_sha256"])
    return backup

def saved():
    if not BACKUP.is_file():raise RuntimeError("Run preflight first")
    return json.loads(BACKUP.read_text(encoding="utf-8"))

def verify_old(backup):
    if autos()!=backup["autos_sha256"]:
        raise RuntimeError("An automation changed; stop")
    m=model()
    if m["meta"]!=backup["meta"] or m["params"]!=backup["params"]:
        raise RuntimeError("Model changed after preflight")
    return m

def register():
    backup=saved()
    m=verify_old(backup)
    if read_tool(NEW_TOOL):
        raise RuntimeError("Tool already registered")
    code=source()
    if hashlib.sha256(code.encode()).hexdigest()!=backup["tool_source_sha256"]:
        raise RuntimeError("Tool source changed")
    item=api("POST","/api/v1/tools/create",{
       "id":NEW_TOOL,"name":"Twelve Data Global Market Research",
       "content":code,"commit_message":"Add authenticated global research feed via existing Contabo bridge",
       "meta":{"description":"Global market research only; no broker operations"}
    })
    if not item or item.get("id")!=NEW_TOOL:raise RuntimeError("Tool creation failed")
    t=read_tool(NEW_TOOL)
    if not t or [x.get("name") for x in t.get("specs",[])]!=["twelve_data_research"]:
        raise RuntimeError("Incorrect registered specs")
    verify_old(backup)
    print("TWELVE_REGISTER_PASS",NEW_TOOL,"methods",["twelve_data_research"])

def bind():
    backup=saved()
    m=verify_old(backup)
    t=read_tool(NEW_TOOL)
    if not t or [x.get("name") for x in t.get("specs",[])]!=["twelve_data_research"]:
        raise RuntimeError("Tool not correctly registered")
    meta=deepcopy(m["meta"])
    params=deepcopy(m["params"])
    if MARKER in str(params.get("system","")):
        raise RuntimeError("New prompt already present")
    meta["toolIds"]=OLD_IDS+[NEW_TOOL]
    params["system"]=params.get("system","")+PROMPT
    response=api("POST","/api/v1/models/model/update",model_form(m,meta,params))
    if not response or response.get("id")!=MODEL:
        raise RuntimeError("Model update failed")
    verify()
    print("TWELVE_MODEL_BIND_PASS","tool_count",5,"prompt_additional_chars",len(PROMPT))

def verify():
    backup=saved()
    m=model()
    expected=OLD_IDS+[NEW_TOOL]
    if m["meta"].get("toolIds")!=expected:
        raise RuntimeError("Attached tool list differs from expected 5")
    oldmeta=backup["meta"]
    for k,v in oldmeta.items():
        if k!="toolIds" and m["meta"].get(k)!=v:
            raise RuntimeError("Unexpected changed model metadata field "+k)
    oldparams=backup["params"]
    if m["params"].get("system","")!=oldparams.get("system","")+PROMPT:
        raise RuntimeError("Original prompt differs")
    for k,v in oldparams.items():
        if k!="system" and m["params"].get(k)!=v:
            raise RuntimeError("Non-system parameter changed: "+k)
    if m["base_model_id"]!=backup["base_model_id"] or m["is_active"]!=backup["is_active"]:
        raise RuntimeError("Model base/active flags changed")
    if autos()!=backup["autos_sha256"]:
        raise RuntimeError("Original schedules changed")
    t=read_tool(NEW_TOOL)
    if not t or [x.get("name") for x in t.get("specs",[])]!=["twelve_data_research"]:
        raise RuntimeError("Research method missing")
    print("TWELVE_VERIFY_PASS","tool_ids",expected,
          "automations",4,"skills",len(m["meta"].get("skillIds") or []),
          "knowledge",len(m["meta"].get("knowledge") or []),
          "original_prompt_preserved",True)

def refresh_registry():
    models=api("GET","/api/v1/models?refresh=true")
    items=models.get("data") if isinstance(models,dict) else models
    matches=[x for x in items if x.get("id")==MODEL] if isinstance(items,list) else []
    if len(matches)!=1:raise RuntimeError("Updated model not in registry")
    meta=(matches[0].get("info") or {}).get("meta") or matches[0].get("meta") or {}
    ids=meta.get("toolIds") or []
    if ids!=OLD_IDS+[NEW_TOOL]:
        raise RuntimeError("In-memory model registry has outdated tool ids")
    print("TWELVE_REGISTRY_REFRESH_PASS","tool_count",len(ids))
    return ids

def rollback():
    backup=saved()
    m=model()
    ids=m["meta"].get("toolIds")
    if ids not in (OLD_IDS,OLD_IDS+[NEW_TOOL]):
        raise RuntimeError("Other tool changes detected; manual rollback required")
    if ids==OLD_IDS+[NEW_TOOL]:
        api("POST","/api/v1/models/model/update",
            model_form(m,backup["meta"],backup["params"]))
    t=read_tool(NEW_TOOL)
    if t:
        api("DELETE","/api/v1/tools/id/"+NEW_TOOL+"/delete")
    again=model()
    if again["meta"]!=backup["meta"] or again["params"]!=backup["params"]:
        raise RuntimeError("Original model was not restored")
    if autos()!=backup["autos_sha256"]:
        raise RuntimeError("Original schedules changed")
    api("GET","/api/v1/models?refresh=true")
    print("TWELVE_ROLLBACK_PASS","prior_tool_count",len(OLD_IDS))

if __name__=="__main__":
    mode=sys.argv[1] if len(sys.argv)>1 else "preflight"
    actions={"preflight":preflight,"register":register,"bind":bind,
             "verify":verify,"refresh":refresh_registry,"rollback":rollback}
    if mode not in actions:raise SystemExit("Invalid mode")
    actions[mode]()

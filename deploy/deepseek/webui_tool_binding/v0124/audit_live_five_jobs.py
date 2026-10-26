#!/usr/bin/env python3
"""Read-only verification of existing five DeepSeek WebUI automations after v0.12.4.

No tool or model calls, no broker communication, no credentials, no writes.
Reads saved WebUI SQLite metadata and only printed function name/count receipts.
"""
import datetime as dt
import json
import sqlite3
from collections import Counter
from pathlib import Path
from zoneinfo import ZoneInfo

DB=Path("/app/backend/data/webui.db")
MODEL="trading-operations--deepseek"
EXPECTED={
    "Morning Research Runner",
    "US CONTROLLER",
    "US OPEN",
    "US MIDDAY",
    "US CLOSE",
}
EXPECTED_TOOLS={
    "trading_212_demo_gateway_tool",
    "market_data_gateway",
    "contabo_command_bridge",
    "trading_brain_research_context",
    "twelve_data_global_research",
}
UK=ZoneInfo("Europe/London")
UTC=dt.timezone.utc
def js(s, fallback=None):
    try: return json.loads(s) if isinstance(s,str) else s
    except Exception: return fallback

def stamp(n):
    if n is None: return None
    v=int(n)
    factor=1e9 if v>10**17 else 1e3 if v>10**11 else 1
    return dt.datetime.fromtimestamp(v/factor,UTC).isoformat(timespec="seconds")

def get(prefix,name):
    return name.startswith(prefix)

def call_summary(output):
    out=js(output,[]) or []
    if not isinstance(out,list): return {"function_calls":0,"matched_outputs":0,"function_names":[]}
    calls=[x for x in out if isinstance(x,dict) and x.get("type")=="function_call"]
    outputs={x.get("call_id") for x in out if isinstance(x,dict) and x.get("type")=="function_call_output"}
    return {
      "function_calls":len(calls),
      "matched_outputs":sum(x.get("call_id") in outputs for x in calls),
      "function_names":sorted(set(str(x.get("name")) for x in calls)),
    }

def main():
    # Standard mode=ro, NOT immutable, so any active WAL is visible.
    db=sqlite3.connect(DB.as_uri()+"?mode=ro",uri=True, timeout=15)
    db.row_factory=sqlite3.Row
    try:
        model=db.execute("select meta from model where id=?",(MODEL,)).fetchone()
        if not model: raise AssertionError("DeepSeek owner model missing")
        toolids=set((js(model["meta"],{}) or {}).get("toolIds") or [])
        assert toolids==EXPECTED_TOOLS, ("Bound tools mismatch", sorted(toolids))
        rows=db.execute("select id,name,is_active,data,last_run_at,next_run_at from automation").fetchall()
        matched=[]
        for a in rows:
            meta=js(a["data"],{}) or {}
            if meta.get("model_id") != MODEL: continue
            matched.append(a)
        assert len(matched)==5, ("Wrong number of existing owner automations",len(matched))
        print("WEBUI_AFTER_UPGRADE_AUDIT", "UTC_NOW",dt.datetime.now(UTC).isoformat(timespec="seconds"),
              "owner_models",1,"bound_tools",len(toolids))
        allgood=True
        for prefix in sorted(EXPECTED):
            arr=[a for a in matched if get(prefix,a["name"])]
            assert len(arr)==1,(prefix,len(arr))
            a=arr[0]
            assert a["is_active"],f"{prefix} is inactive"
            info={"job":prefix,"active":True,"last_run":stamp(a["last_run_at"]),
                  "next_run":stamp(a["next_run_at"])}
            recs=db.execute(
               "select status,error,chat_id,created_at from automation_run "
               "where automation_id=? order by created_at desc limit 2",(a["id"],)
            ).fetchall()
            info["recent_runs"]=[]
            for r in recs:
                result={"created_at":stamp(r["created_at"]),"status":r["status"],
                        "error_present":bool(r["error"])}
                if r["chat_id"]:
                    msg=db.execute(
                      "select output,done,model_id from chat_message "
                      "where chat_id=? and role='assistant' order by created_at desc limit 1",
                       (r["chat_id"],)
                    ).fetchone()
                    if msg:
                       result["assistant_done"]=bool(msg["done"])
                       result.update(call_summary(msg["output"]))
                    else: result["assistant_record"]="NOT_FOUND"
                info["recent_runs"].append(result)
            print(json.dumps(info,sort_keys=True))
        print("WEBUI_FIVE_JOB_AUDIT_PASS", "active_jobs",len(matched),
              "bound_tool_ids",len(toolids),"broker_requests_by_audit",0,
              "model_calls_by_audit",0)
    finally: db.close()
if __name__=="__main__":
    main()

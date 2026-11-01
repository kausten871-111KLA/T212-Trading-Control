#!/usr/bin/env python3
"""Read-only WebUI scheduled tool acceptance. No API, broker, model or network calls."""
import argparse
import datetime as dt
import json
import sqlite3
from collections import Counter
from zoneinfo import ZoneInfo

PHASE_NAMES = ("US OPEN", "US MIDDAY", "US CLOSE")
TOOL_NAMES = {
    "trading_dashboard", "list_positions", "list_orders", "recent_order_history",
    "place_market_order_with_intent", "reconcile_order_intent", "place_market_order",
    "candidate_scan", "top_movers", "most_active", "snapshots",
    "latest_quotes", "health_check", "market_clock",
}
BROKER_PREFIXES = ("place_", "cancel_", "reconcile_", "get_order", "get_position")

def unix_seconds(value):
    if value is None:
        return None
    n = float(value)
    return n / (1e9 if n > 1e17 else 1e3 if n > 1e11 else 1)

def utc_time(value):
    t = unix_seconds(value)
    return dt.datetime.fromtimestamp(t, dt.timezone.utc) if t is not None else None

def as_json(value, default=None):
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default

def summarise_output(items):
    calls = [x for x in items if isinstance(x, dict) and x.get("type") == "function_call"]
    results = [x for x in items if isinstance(x, dict) and x.get("type") == "function_call_output"]
    ids = {x.get("call_id") for x in results if x.get("call_id")}
    called = Counter(str(x.get("name") or "<unnamed>") for x in calls)
    confirmed = Counter(str(x.get("name") or "<unnamed>") for x in calls if x.get("call_id") in ids)
    tool_calls = {name: count for name, count in called.items()
                  if name in TOOL_NAMES or name.startswith(BROKER_PREFIXES)}
    tool_confirmed = {name: count for name, count in confirmed.items()
                      if name in TOOL_NAMES or name.startswith(BROKER_PREFIXES)}
    return {"all_function_calls": len(calls), "returned_outputs": len(results),
            "tool_calls": tool_calls, "tool_outputs_recorded": tool_confirmed,
            "output_missing_count": max(0, len(calls) - len([x for x in calls if x.get("call_id") in ids]))}

def report(path, date, phase, timezone):
    zone = ZoneInfo(timezone)
    conn = sqlite3.connect("file:" + path + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT id, name, is_active, last_run_at, next_run_at, user_id, data FROM automation").fetchall()
        selections = [x for x in rows if x["name"].upper().startswith("US ")]
        assert len(selections) == 3, f"Expected exactly 3 original trading automations; got {len(selections)}"
        out = {"date": date, "timezone": timezone, "checks": []}
        for a in selections:
            name = a["name"]
            key = next((s for s in PHASE_NAMES if name.upper().startswith(s)), None)
            if phase != "ALL" and phase != key:
                continue
            data = as_json(a["data"], {}) or {}
            model_ok = data.get("model_id") == "trading-operations--deepseek"
            model = conn.execute("SELECT user_id,meta FROM model WHERE id=?", ("trading-operations--deepseek",)).fetchone()
            configured = set((as_json(model["meta"], {}) or {}).get("toolIds") or []) if model else set()
            tool_ids_ok = {"trading_212_demo_gateway_tool","market_data_gateway"} <= configured
            owned = bool(model and model["user_id"] == a["user_id"])
            recent = conn.execute("SELECT id, chat_id, status, created_at FROM automation_run "
                                  "WHERE automation_id=? ORDER BY created_at DESC LIMIT 12", (a["id"],)).fetchall()
            relevant = [r for r in recent if utc_time(r["created_at"]).astimezone(zone).date().isoformat() == date]
            run = relevant[0] if relevant else None
            entry = {"phase": key, "active": bool(a["is_active"]),
                     "stored_model_matches": model_ok, "model_tool_ids_present": tool_ids_ok,
                     "model_owner_matches": owned,
                     "next_utc": utc_time(a["next_run_at"]).isoformat() if a["next_run_at"] else None,
                     "run": "PENDING" if not run else "RECORDED"}
            if run:
                entry["scheduler_status"] = run["status"]
                entry["run_started_utc"] = utc_time(run["created_at"]).isoformat()
                assistant = conn.execute("SELECT output, done, model_id FROM chat_message "
                                         "WHERE chat_id=? AND role='assistant' ORDER BY created_at DESC LIMIT 1",
                                         (run["chat_id"],)).fetchone()
                if assistant:
                    entry["assistant_done"] = bool(assistant["done"])
                    entry.update(summarise_output(as_json(assistant["output"], []) or []))
                    entry["tool_acceptance"] = ("PASS_FUNCTION_CALLED_AND_OUTPUT_RECORDED"
                        if entry["tool_outputs_recorded"] else
                        "NO_GATEWAY_OR_ALPACA_FUNCTION_OUTPUT_RECORDED")
                else:
                    entry["tool_acceptance"] = "NO_ASSISTANT_MESSAGE"
            out["checks"].append(entry)
        return out
    finally:
        conn.close()

def selftest():
    fixture=[
        {"type":"function_call","call_id":"1","name":"trading_dashboard"},
        {"type":"function_call_output","call_id":"1","output":[{"type":"text","text":"masked"}]},
        {"type":"function_call","call_id":"2","name":"candidate_scan"},
        {"type":"function_call","call_id":"3","name":"view_skill"},
    ]
    r=summarise_output(fixture)
    assert r["tool_outputs_recorded"] == {"trading_dashboard":1}
    assert r["tool_calls"] == {"trading_dashboard":1,"candidate_scan":1}
    assert r["output_missing_count"] == 2
    assert not summarise_output([])["tool_outputs_recorded"]
    assert unix_seconds(1792416904211116857) > 1700000000
    print("SELFTEST_PASS")

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--db",default="/app/backend/data/webui.db")
    parser.add_argument("--date",default=dt.datetime.now(ZoneInfo("Europe/London")).date().isoformat())
    parser.add_argument("--phase",choices=("ALL",)+PHASE_NAMES,default="US OPEN")
    parser.add_argument("--selftest",action="store_true")
    args=parser.parse_args()
    if args.selftest:selftest();return
    print(json.dumps(report(args.db,args.date,args.phase,"Europe/London"),indent=2,ensure_ascii=False))

if __name__=="__main__":
    main()

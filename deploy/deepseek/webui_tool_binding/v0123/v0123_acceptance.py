#!/usr/bin/env python3
"""Read-only acceptance for the exact user-configured WebUI 0.12.3 installation.

Run inside upgraded WebUI: python /tmp/v0123_acceptance.py
No inference, broker orders, shell commands or remote API calls.
"""
import asyncio
import json
import sqlite3
import urllib.request
from fastapi import FastAPI, Request
from open_webui.models.models import Models
from open_webui.models.users import Users
from open_webui.utils.automations import _resolve_model_defaults
from open_webui.utils.automation_tool_contract import assess_automation_tools
from open_webui.utils.tools import get_tools

MODEL="trading-operations--deepseek"
IDS={"trading_212_demo_gateway_tool","market_data_gateway","contabo_command_bridge"}

async def check():
    with urllib.request.urlopen("http://127.0.0.1:8080/health",timeout=5) as r:
        assert r.status==200
    db=sqlite3.connect("file:/app/backend/data/webui.db?mode=ro",uri=True)
    try:
        assert db.execute("pragma integrity_check").fetchone()[0]=="ok"
        schedules=db.execute("select id,name,is_active from automation where name like 'US %'").fetchall()
        assert len(schedules)==3 and all(v[2] for v in schedules),schedules
        for expected in ("US OPEN","US MIDDAY","US CLOSE"):
            assert sum(row[1].startswith(expected) for row in schedules)==1,expected
        m=db.execute("select meta from model where id=?",(MODEL,)).fetchone()
        assert m
        tool_ids=json.loads(m[0]).get("toolIds",[])
        assert IDS<=set(tool_ids)
        for tool in IDS:
            assert db.execute("select id from tool where id=?",(tool,)).fetchone(),tool
    finally:
        db.close()
    model=await Models.get_model_by_id(MODEL)
    assert model
    user=Users.get_user_by_id(model.user_id)
    if asyncio.iscoroutine(user):user=await user
    assert user
    import types
    fake=types.SimpleNamespace(state=types.SimpleNamespace(MODELS={MODEL:{"info":{"meta":{}}}}))
    defaults=await _resolve_model_defaults(fake,MODEL)
    assert IDS<=set(defaults.get("tool_ids",[]))
    app=FastAPI()
    req=Request({"type":"http","app":app,"headers":[]})
    params={"__user__":{"id":user.id,"name":user.name,"email":user.email,"role":user.role},
            "__model__":{"id":MODEL},"__messages__":[],"__files__":[]}
    got=await get_tools(req,tool_ids,user,params)
    resolved={spec.get("tool_id") for spec in got.values()}
    assert IDS<=resolved,(IDS-resolved)
    assert len(got)>=28,len(got)
    receipt=assess_automation_tools(tool_ids,tool_ids,got)
    assert receipt.ready and not receipt.missing_ids
    assert "alpha_vantage_daily" in json.dumps(
        next(spec["spec"] for spec in got.values() if spec.get("tool_id")=="contabo_command_bridge")
    ),"Alpha Vantage bridge schema missing"
    print("V0123_ACCEPTANCE_PASS",json.dumps({
        "status":"healthy",
        "automations":len(schedules),
        "model_tool_ids":sorted(tool_ids),
        "resolved_function_count":len(got),
        "resolved_ids":sorted(resolved),
        "alpha_vantage_schema_present":True,
        "trading_live_enabled_by_test":False,
        "orders_placed_by_test":0
    },sort_keys=True),flush=True)

if __name__=="__main__":
    asyncio.run(check())

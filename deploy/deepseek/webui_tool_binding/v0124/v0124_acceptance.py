#!/usr/bin/env python3
"""Post-cutover production acceptance. Reads WebUI metadata and tool descriptors only.

For supervised deployment before the first Monday 26 Oct 2026 trading job.
Does not execute inference, broker calls, external HTTP, or alter automation rows.
The only HTTP call is localhost:8080/health. No secrets are printed.
"""
import asyncio, datetime, json, os, sqlite3, sys, types, urllib.request
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
    with urllib.request.urlopen('http://127.0.0.1:8080/health',timeout=7) as health:
        assert health.status==200, 'WebUI health endpoint unavailable'
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
            now=datetime.datetime.now(datetime.timezone.utc)
            first_run=datetime.datetime(2026,10,26,12,0,tzinfo=datetime.timezone.utc)
            if now<first_run:
                assert (dt.year,dt.month,dt.day,dt.hour,dt.minute)==(2026,10,26,*clock),(
                     f"{prefix} next UTC run mismatch: {dt.isoformat()} expected Mon 26 Oct {clock}")
            else:
                assert dt>=now-datetime.timedelta(minutes=2),(
                     f"{prefix} next run is stale: {dt.isoformat()}")
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
    print("V0124_PRODUCTION_ACCEPTANCE_PASS","automations",len(jobs),
          "bound_tools",len(tool_ids),"resolved_functions",len(got),
          "python",sys.version.split()[0],
          "provider_calls",0,"broker_orders",0,flush=True)
asyncio.run(verify())
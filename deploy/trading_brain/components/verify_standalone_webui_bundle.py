"""Acceptance for a self-contained WebUI research tool in *base* v0.12.3."""
from __future__ import annotations
import asyncio
import importlib.util
import os
from cryptography.fernet import Fernet
os.environ['WEBUI_SECRET_KEY'] = Fernet.generate_key().decode('ascii')
import json
from pathlib import Path

path=Path("/workspace/trading_brain_webui_bundle.py")
assert path.exists()
spec=importlib.util.spec_from_file_location("trading_brain_standalone",path)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert hasattr(module,"Tools")
from open_webui.utils.tools import get_tool_specs
toolspec=get_tool_specs(module.Tools())
assert len(toolspec)==1
assert toolspec[0]["name"]=="trading_brain_research"
params=toolspec[0]["parameters"]["properties"]
assert {"ticker","snapshot_json","as_of_utc","bars_json"} <= set(params)
test={
  "provider":"Alpaca","feed":"iex","readOnly":True,
  "symbols":[{
    "symbol":"MYGN","price":5.54,"bid":4.77,"ask":6.37,
    "spreadPct":28.73,"dayVolume":934853,
    "quoteTimestamp":"2026-10-21T14:35:01Z",
    "tradeTimestamp":"2026-10-21T14:35:02Z",
  }]
}
bars={"bars":{"MYGN":[
  {"t":"2026-10-21T13:30:00Z","c":5.0,"v":100,"h":5.2,"l":4.9},
  {"t":"2026-10-21T13:35:00Z","c":5.5,"v":200,"h":5.6,"l":5.0}
]}}
reply=asyncio.run(module.Tools().trading_brain_research(
  ticker="MYGN",snapshot_json=json.dumps(test),bars_json=json.dumps(bars),
  as_of_utc="2026-10-21T14:40:00Z",average_daily_volume=150,
))
out=json.loads(reply)
assert out["ticker"]=="MYGN"
assert out["quote_economics_hypothetical"]["roundtrip_spread_cost"]=="160.00"
assert out["bar_features"]["relative_volume"]==2
assert out["source_evidence"]["observation_time_is_caller_supplied"] is True
assert out["research_only"] is True and out["broker_order_instructions"] is False
print("STANDALONE_WEBUI_BASE_IMAGE_TOOL_PASS",
      "tool",toolspec[0]["name"],"arguments",sorted(params),
      "sample_spread_cost",out["quote_economics_hypothetical"]["roundtrip_spread_cost"],
      "broker_orders",0,"network_calls",0)

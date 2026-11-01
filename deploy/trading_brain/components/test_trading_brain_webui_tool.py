"""Tests the staged WebUI tool without registering it with the running model."""
import asyncio
import json
import unittest
from pathlib import Path

from trading_brain_research_tool import Tools

BENCHMARK=Path(__file__).resolve().parent.parent/"benchmark"
FIXTURE=json.loads((BENCHMARK/"alpaca_eod_20261020_20.json").read_text())
DECISIONS=json.loads(
    (BENCHMARK/"results/tradingagents_native_real_3symbols.json").read_text())
D_BY={x["ticker"]:x for x in DECISIONS["decisions"]}


class ToolSmoke(unittest.IsolatedAsyncioTestCase):
    async def test_mygn_native_buy_advisory_not_overwritten(self):
        output=await Tools().trading_brain_research(
            ticker="MYGN", snapshot_json=json.dumps(FIXTURE),
            as_of_utc="2026-10-21T14:00:00Z",
            decision_json=json.dumps(D_BY["MYGN"]),
        )
        obj=json.loads(output)
        self.assertEqual(obj["ticker"],"MYGN")
        self.assertEqual(obj["quote_economics_hypothetical"]["roundtrip_spread_cost"],"160.00")
        self.assertEqual(obj["decision_quality_advisory"]["action"],"BUY")
        self.assertEqual(obj["history_as_of"],[])
        self.assertFalse(obj["broker_order_instructions"])

    async def test_missing_vwap_stays_null(self):
        output=await Tools().trading_brain_research(
            ticker="BRZE",snapshot_json=json.dumps(FIXTURE),
            as_of_utc="2026-10-21T14:00:00Z")
        obj=json.loads(output)
        self.assertIsNone(obj["bar_features"]["volume_weighted_price"])
        self.assertIsNone(obj["bar_features"]["relative_volume"])

    async def test_invalid_json_fails_closed(self):
        output=await Tools().trading_brain_research(
            ticker="MYGN",snapshot_json="{bad",
            as_of_utc="2026-10-21T14:00:00Z")
        obj=json.loads(output)
        self.assertFalse(obj["ok"])
        self.assertEqual(obj["error"],"invalid_research_input")

    async def test_future_observation_rejected(self):
        output=await Tools().trading_brain_research(
            ticker="MYGN",snapshot_json=json.dumps(FIXTURE),
            as_of_utc="2026-10-20T18:00:00Z")
        self.assertFalse(json.loads(output)["ok"])

    async def test_missing_symbol_rejected(self):
        output=await Tools().trading_brain_research(
            ticker="MISSING",snapshot_json=json.dumps(FIXTURE),
            as_of_utc="2026-10-21T14:00:00Z")
        self.assertFalse(json.loads(output)["ok"])

    async def test_bounded_scenario_not_order_instruction(self):
        output=await Tools().trading_brain_research(
            ticker="MYGN",snapshot_json=json.dumps(FIXTURE),
            as_of_utc="2026-10-21T14:00:00Z",
            scenario_quantity=100_001)
        obj=json.loads(output)
        self.assertFalse(obj["ok"])
        self.assertEqual(obj["broker_orders"],0)

    async def test_no_payment_or_broker_import(self):
        source=(Path(__file__).parent/"trading_brain_research_tool.py").read_text()
        for forbidden in ("requests.", "httpx.", "place_market_order",
                          "import openai", "import subprocess",
                          "trading212_demo_gateway"):
            self.assertNotIn(forbidden, source)

    async def test_payload_limit(self):
        output=await Tools().trading_brain_research(
            ticker="MYGN",snapshot_json=" "*60001,
            as_of_utc="2026-10-21T14:00:00Z")
        self.assertFalse(json.loads(output)["ok"])


if __name__=="__main__":
    unittest.main()

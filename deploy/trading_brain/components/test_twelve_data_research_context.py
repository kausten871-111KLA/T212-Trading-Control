"""Global Twelve Data -> existing Trading Brain adapter offline acceptance tests."""
from __future__ import annotations
import asyncio
import json
import unittest

from market_gateway_normalizer import normalise_snapshot,normalise_bars
from research_context import compile_context
from trading_brain_research_tool import Tools

ASOF="2026-10-21T15:00:00Z"
QUOTE={
  "ok":True,"provider":"Twelve Data","endpoint":"quote",
  "requested_symbol":"TSCO","symbol":"TSCO","exchange":"LSE",
  "mic_code":"XLON","currency":"GBX","exchange_timezone":"Europe/London",
  "datetime":"2026-10-21","close":"310.50","previous_close":"306.1",
  "change_percent":"1.44","volume":"16507200","bid":None,"ask":None,
}
SERIES={
  "ok":True,"provider":"Twelve Data","endpoint":"time_series",
  "requested_symbol":"TSCO","bar_time_basis":"UTC_requested_provider_series",
  "meta":{"interval":"5min","currency":"GBX","mic_code":"XLON"},
  "values":[
    {"datetime":"2026-10-21 14:05:00","open":"310.00","high":"314.00",
     "low":"309.00","close":"312.50","volume":"200"},
    {"datetime":"2026-10-21 14:00:00","open":"308.00","high":"311.00",
     "low":"307.00","close":"310.00","volume":"100"},
  ]
}


class TwelveBrainTests(unittest.IsolatedAsyncioTestCase):
    async def test_quote_maps_to_currency_and_mic_without_fake_bid(self):
        snap=normalise_snapshot(QUOTE,ticker="TSCO",as_of_utc=ASOF)
        self.assertEqual(snap["observation"]["currency"],"GBX")
        self.assertEqual(snap["observation"]["mic_code"],"XLON")
        self.assertIsNone(snap["observation"]["bid"])
        result=compile_context(snap,ticker="TSCO",as_of_utc=ASOF)
        data=result["source_evidence"]["observation"]
        self.assertEqual(data["currency"],"GBX")
        self.assertEqual(data["mic_code"],"XLON")
        self.assertIsNone(result["quote_economics_hypothetical"]["roundtrip_spread_cost"])
        self.assertFalse(result["broker_order_instructions"])

    async def test_time_series_intraday_preserves_explicit_utc(self):
        bars=normalise_bars(SERIES,ticker="TSCO")
        self.assertEqual(len(bars),2)
        self.assertEqual(bars[0]["timestamp_utc"],"2026-10-21T14:00:00+00:00")
        self.assertEqual(bars[1]["volume"],"200")
        result=compile_context(normalise_snapshot(QUOTE,ticker="TSCO",as_of_utc=ASOF),
                               ticker="TSCO",as_of_utc=ASOF,bars=bars)
        self.assertEqual(result["bar_features"]["bars"],2)

    async def test_daily_local_dates_are_not_fake_utc_instants(self):
        daily={**SERIES,"bar_time_basis":"exchange_local_date",
               "meta":{"interval":"1day"}}
        with self.assertRaises(ValueError):
            normalise_bars(daily,ticker="TSCO")

    async def test_mismatched_symbol_rejected(self):
        with self.assertRaises(ValueError):
            normalise_snapshot(QUOTE,ticker="AAPL",as_of_utc=ASOF)

    async def test_actual_webui_tool_accepts_twelve_data_json(self):
        out=await Tools().trading_brain_research(
            ticker="TSCO",snapshot_json=json.dumps(QUOTE),
            bars_json=json.dumps(SERIES),as_of_utc=ASOF)
        data=json.loads(out)
        self.assertEqual(data["ticker"],"TSCO")
        self.assertEqual(data["bar_features"]["bars"],2)
        self.assertTrue(data["research_only"])

    async def test_provider_failure_not_silently_accepted(self):
        broken={**QUOTE,"ok":False,"error":"plan_missing"}
        out=await Tools().trading_brain_research(
            ticker="TSCO",snapshot_json=json.dumps(broken),as_of_utc=ASOF)
        self.assertEqual(json.loads(out)["error"],"invalid_research_input")

    async def test_no_daily_market_trading_assumption(self):
        snap=normalise_snapshot(QUOTE,ticker="TSCO",as_of_utc=ASOF)
        result=compile_context(snap,ticker="TSCO",as_of_utc=ASOF)
        self.assertIn("timestamped_bid_ask_quote",result["missing_evidence"])
        self.assertEqual(result["source_evidence"]["observation"]["provider_market_datetime"],
                         "2026-10-21")

if __name__=="__main__":
    unittest.main()

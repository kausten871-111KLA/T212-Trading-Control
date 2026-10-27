"""Regression tests for Alpaca screener session provenance.

No Alpaca API calls, broker orders, model inference or Twelve Data credits.
"""
import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "gateway_movers_session", ROOT / "openwebui/tools/market_data_gateway.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class AlpacaMowerSessionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tool = module.Tools()
        self.market_payload = {
            "gainers": [{"symbol": "A", "percent_change": 51.5}],
            "losers": [{"symbol": "B", "percent_change": -25.0}],
        }

    async def test_closed_market_does_not_claim_current_premarket_movers(self):
        self.tool._get = AsyncMock(side_effect=[
            (self.market_payload, None),
            ({"is_open": False, "timestamp": "2026-10-27T12:00:00Z"}, None),
        ])
        result = json.loads(await self.tool.top_movers(top=20))
        self.assertEqual(result["mover_list_session"], "last_regular_session_not_live_premarket")
        self.assertTrue(result["not_a_live_premarket_gainers_list"])
        self.assertEqual(result["gainers"], self.market_payload["gainers"])
        self.assertEqual(result["losers"], self.market_payload["losers"])
        self.assertEqual(result["orders_submitted_by_tool"], 0)
        self.assertFalse(result["individual_quote_or_trade_timestamps_verified"])
        self.assertEqual(self.tool._get.await_count, 2)

    async def test_regular_market_open_does_not_claim_current_quote_timestamp(self):
        self.tool._get = AsyncMock(side_effect=[
            (self.market_payload, None),
            ({"is_open": True, "timestamp": "2026-10-27T15:00:00Z"}, None),
        ])
        result = json.loads(await self.tool.top_movers())
        self.assertEqual(result["mover_list_session"], "current_regular_session_unverified_quote_age")
        self.assertIs(result["market_clock_is_open"], True)
        self.assertFalse(result["individual_quote_or_trade_timestamps_verified"])
        self.assertEqual(result["gainers"], self.market_payload["gainers"])

    async def test_unavailable_market_clock_fails_to_unknown_not_live(self):
        self.tool._get = AsyncMock(side_effect=[
            (self.market_payload, None),
            (None, "clock_http_503"),
        ])
        result = json.loads(await self.tool.top_movers())
        self.assertEqual(result["mover_list_session"], "unknown_clock_unverified")
        self.assertEqual(result["market_clock_error"], "clock_http_503")
        self.assertEqual(result["gainers"], self.market_payload["gainers"])

    async def test_movers_error_returns_unchanged_and_does_not_call_clock(self):
        self.tool._get = AsyncMock(side_effect=[(None, "movers_rate_limited")])
        self.assertEqual(await self.tool.top_movers(), "movers_rate_limited")
        self.assertEqual(self.tool._get.await_count, 1)


if __name__ == "__main__":
    unittest.main()

"""Offline acceptance for evidence-labelled market insights; no network/broker calls."""
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

from openwebui.tools.market_data_gateway import Tools


def iso(seconds_ago):
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()


class MarketInsightsDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tool = Tools()
        self.tool.candidate_scan = AsyncMock()

    def response(self, candidates, **errors):
        return json.dumps({
            "candidates": candidates,
            "moversError": errors.get("moversError"),
            "mostActiveError": errors.get("mostActiveError"),
            "snapshotError": errors.get("snapshotError"),
        })

    async def test_current_rows_sorted_and_labelled_without_rvol_claim(self):
        self.tool.candidate_scan.return_value = self.response([
            {"symbol": "LOW", "price": 8, "changePctVsPrevClose": 3,
             "dayVolume": 400, "previousVolume": 200,
             "quoteTimestamp": iso(15), "tradeTimestamp": iso(10)},
            {"symbol": "HIGH", "price": 4, "changePctVsPrevClose": 20,
             "dayVolume": 300, "previousVolume": 100,
             "quoteTimestamp": iso(20), "tradeTimestamp": iso(5)},
        ])
        result = json.loads(await self.tool.market_insights_discovery())
        self.assertTrue(result["ok"])
        self.assertEqual([r["symbol"] for r in result["candidates"]], ["HIGH", "LOW"])
        self.assertEqual(result["candidates"][0]["previous_session_volume_ratio"], 3.0)
        self.assertFalse(result["candidates"][0]["volume_ratio_is_rvol"])
        self.assertEqual(result["orders_submitted_by_tool"], 0)
        self.assertTrue(result["not_tradingview_stockanalysis_or_yahoo_data"])
        self.tool.candidate_scan.assert_awaited_once_with(top=20, feed="iex")

    async def test_rejects_stale_future_and_naive_timestamp(self):
        self.tool.candidate_scan.return_value = self.response([
            {"symbol": "STALE", "quoteTimestamp": iso(600)},
            {"symbol": "FUTURE", "tradeTimestamp": iso(-90)},
            {"symbol": "NAIVE", "quoteTimestamp": "2026-10-26T14:30:00"},
            {"symbol": "GOOD", "tradeTimestamp": iso(12)},
        ])
        result = json.loads(await self.tool.market_insights_discovery(max_age_seconds=300))
        self.assertEqual([r["symbol"] for r in result["candidates"]], ["GOOD"])
        self.assertEqual(result["rejected"]["stale_or_future"], 2)
        self.assertEqual(result["rejected"]["missing_or_invalid_timestamp"], 1)

    async def test_no_provider_response_does_not_invent_candidates(self):
        self.tool.candidate_scan.return_value = "Alpaca data API error 403"
        result = json.loads(await self.tool.market_insights_discovery())
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "candidate_scan_invalid_response")

    async def test_invalid_feed_rejected_without_network(self):
        result = json.loads(await self.tool.market_insights_discovery(feed="sip"))
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "unsupported_feed")
        self.tool.candidate_scan.assert_not_awaited()

    async def test_all_stale_is_explicit_empty_not_success(self):
        self.tool.candidate_scan.return_value = self.response([
            {"symbol": "OLD", "tradeTimestamp": iso(4000)}
        ], moversError="plan restricted")
        result = json.loads(await self.tool.market_insights_discovery())
        self.assertFalse(result["ok"])
        self.assertEqual(result["candidate_count"], 0)
        self.assertEqual(result["movers_error"], "plan restricted")
        self.assertEqual(result["rejected"]["stale_or_future"], 1)


if __name__ == "__main__":
    unittest.main()

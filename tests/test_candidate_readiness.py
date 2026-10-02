import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from openwebui.tools.catalyst_handoff_queue import CatalystHandoffQueue
from worker.run_candidate_readiness import ReadinessError, build_readiness, normalize_broker_dashboard


NOW = datetime(2026, 10, 2, 14, 30, tzinfo=timezone.utc)


def candidate(symbol="ABC", scanner_state="qualified"):
    return {
        "symbol": symbol,
        "t212_ticker": f"{symbol}_US_EQ",
        "scanner_state": scanner_state,
        "tradable": True,
        "spread_pct": 1.0,
        "price": 10,
        "rel_vol": 3,
        "dollar_vol": 2_000_000,
        "tier_state": {"current_tier": 1},
    }


def review(symbol="ABC", disposition="qualify"):
    return {
        "symbol": symbol,
        "reason_tag": "FRESH_NEWS",
        "catalyst_state": "confirmed",
        "headline": "Test filing",
        "source": "https://example.test/filing",
        "source_ts": "2026-10-02T14:00:00Z",
        "mechanism": "Test mechanism",
        "risk_flags": [],
        "disposition": disposition,
        "confidence": 0.8,
    }


def dashboard(live=False):
    return {
        "environment": "DEMO",
        "gatewayVersion": "0.3.0-candidate",
        "account": {
            "totalValue": 288.28,
            "cash": {"availableToTrade": 288.28},
            "currency": "GBP",
        },
        "positions": [],
        "pendingOrders": [],
        "liveTradingEnabled": live,
    }


class CountingFetcher:
    def __init__(self, value):
        self.value = value
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.value


class CandidateReadinessTests(unittest.TestCase):
    def completed_event(self, queue, item, result):
        event = queue.enqueue(item, now=NOW)["event"]
        queue.claim(event["id"], now=NOW)
        queue.acknowledge(event["id"], result=result, now=NOW)

    def test_broker_is_not_called_without_prequalified_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            queue = CatalystHandoffQueue(Path(td) / "queue.jsonl")
            self.completed_event(queue, candidate(scanner_state="watch-illiquid"), review())
            fetcher = CountingFetcher(dashboard())
            output = build_readiness(queue, fetcher, observed_at=NOW)
            self.assertEqual(output["state"], "NO_CANDIDATE_READY")
            self.assertEqual(fetcher.calls, 0)

    def test_qualified_candidate_triggers_one_broker_read_and_waits_for_proposal(self):
        with tempfile.TemporaryDirectory() as td:
            queue = CatalystHandoffQueue(Path(td) / "queue.jsonl")
            self.completed_event(queue, candidate(), review())
            fetcher = CountingFetcher(dashboard())
            output = build_readiness(queue, fetcher, observed_at=NOW)
            self.assertEqual(fetcher.calls, 1)
            self.assertEqual(output["state"], "READY_FOR_PROPOSAL")
            self.assertEqual(output["candidates"][0]["decision"], "READY_FOR_PROPOSAL")
            self.assertEqual(output["candidates"][0]["risk_gate_state"], "PENDING_IMMUTABLE_PROPOSAL")
            self.assertEqual(output["orders_submitted"], 0)
            self.assertFalse(output["live_trading_enabled"])

    def test_unknown_or_watch_catalyst_does_not_call_broker(self):
        with tempfile.TemporaryDirectory() as td:
            queue = CatalystHandoffQueue(Path(td) / "queue.jsonl")
            item = review(disposition="watch")
            item["catalyst_state"] = "unknown"
            item["source"] = ""
            self.completed_event(queue, candidate(), item)
            fetcher = CountingFetcher(dashboard())
            output = build_readiness(queue, fetcher, observed_at=NOW)
            self.assertEqual(fetcher.calls, 0)
            self.assertIn("CATALYST_NOT_VERIFIED", output["candidates"][0]["reasons"])

    def test_live_or_incomplete_broker_dashboard_fails_closed(self):
        with self.assertRaises(ReadinessError):
            normalize_broker_dashboard(dashboard(live=True), observed_at=NOW)
        incomplete = dashboard()
        del incomplete["account"]["totalValue"]
        with self.assertRaises(ReadinessError):
            normalize_broker_dashboard(incomplete, observed_at=NOW)

    def test_broker_failure_blocks_candidate_without_order(self):
        with tempfile.TemporaryDirectory() as td:
            queue = CatalystHandoffQueue(Path(td) / "queue.jsonl")
            self.completed_event(queue, candidate(), review())
            output = build_readiness(queue, lambda: "429 rate limited", observed_at=NOW)
            self.assertEqual(output["state"], "BLOCKED")
            self.assertIn("BROKER_READBACK_UNAVAILABLE", output["candidates"][0]["reasons"])
            self.assertEqual(output["orders_submitted"], 0)


if __name__ == "__main__":
    unittest.main()

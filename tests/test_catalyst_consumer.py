import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from openwebui.tools.catalyst_handoff_queue import CatalystHandoffQueue
from worker.run_catalyst_consumer import ReviewError, consume, validate_result


NOW = datetime(2026, 10, 2, 14, 30, tzinfo=timezone.utc)


def candidate(symbol):
    return {
        "symbol": symbol,
        "t212_ticker": f"{symbol}_US_EQ",
        "price": 10,
        "change_pct": 12,
        "rel_vol": 3,
        "spread_pct": 1,
        "tier_state": {"current_tier": 1},
    }


def result(symbol):
    return {
        "symbol": symbol,
        "reason_tag": "FRESH_NEWS",
        "catalyst_state": "confirmed",
        "headline": "Test filing",
        "source": "https://example.test/filing",
        "source_ts": "2026-10-02T14:00:00Z",
        "mechanism": "Test mechanism",
        "risk_flags": [],
        "disposition": "watch",
        "confidence": 0.8,
    }


class StaticReviewer:
    def review(self, item):
        return result(item["symbol"])


class BrokenReviewer:
    def review(self, item):
        raise ReviewError("provider unavailable")


class CatalystConsumerTests(unittest.TestCase):
    def make_queue(self, td, max_per_day=20):
        return CatalystHandoffQueue(Path(td) / "queue.jsonl", max_per_day=max_per_day)

    def test_successful_consumer_acknowledges_and_keeps_no_order_authority(self):
        with tempfile.TemporaryDirectory() as td:
            queue = self.make_queue(td)
            queue.enqueue(candidate("ABC"), now=NOW)
            output = consume(queue, StaticReviewer(), now=NOW)
            self.assertEqual(output["processed"], 1)
            self.assertEqual(output["queue"]["done"], 1)
            self.assertEqual(output["orders_submitted"], 0)
            self.assertFalse(output["live_trading_enabled"])

    def test_consumer_is_bounded_to_five(self):
        with tempfile.TemporaryDirectory() as td:
            queue = self.make_queue(td)
            for index in range(6):
                queue.enqueue(candidate(f"S{index}"), now=NOW)
            output = consume(queue, StaticReviewer(), max_per_run=99, now=NOW)
            self.assertEqual(output["processed"], 5)
            self.assertEqual(output["queue"]["pending"], 1)

    def test_retry_then_terminal_failure(self):
        with tempfile.TemporaryDirectory() as td:
            queue = self.make_queue(td)
            queue.enqueue(candidate("ABC"), now=NOW)
            first = consume(queue, BrokenReviewer(), max_attempts=2, now=NOW)
            self.assertEqual(len(first["retried"]), 1)
            second = consume(queue, BrokenReviewer(), max_attempts=2, now=NOW + timedelta(seconds=1))
            self.assertEqual(len(second["failed"]), 1)
            self.assertEqual(second["queue"]["failed"], 1)

    def test_expired_claim_is_recovered_after_crash(self):
        with tempfile.TemporaryDirectory() as td:
            queue = self.make_queue(td)
            event = queue.enqueue(candidate("ABC"), now=NOW)["event"]
            queue.claim(event["id"], lease_seconds=30, now=NOW)
            output = consume(queue, StaticReviewer(), now=NOW + timedelta(seconds=31))
            self.assertEqual(output["queue"]["done"], 1)
            self.assertEqual(output["completed"][0]["result"]["symbol"], "ABC")

    def test_active_claim_is_not_double_processed(self):
        with tempfile.TemporaryDirectory() as td:
            queue = self.make_queue(td)
            event = queue.enqueue(candidate("ABC"), now=NOW)["event"]
            queue.claim(event["id"], lease_seconds=30, now=NOW)
            output = consume(queue, StaticReviewer(), now=NOW + timedelta(seconds=20))
            self.assertEqual(output["processed"], 0)

    def test_daily_budget_and_deduplication(self):
        with tempfile.TemporaryDirectory() as td:
            queue = self.make_queue(td, max_per_day=1)
            first = queue.enqueue(candidate("ABC"), now=NOW)
            self.assertTrue(first["queued"])
            self.assertEqual(queue.enqueue(candidate("ABC"), now=NOW)["reason"], "duplicate")
            self.assertEqual(queue.enqueue(candidate("XYZ"), now=NOW)["reason"], "daily_budget_reached")

    def test_result_validation_rejects_symbol_mismatch_and_unsourced_claim(self):
        with self.assertRaises(ReviewError):
            validate_result(candidate("ABC"), result("XYZ"))
        bad = result("ABC")
        bad["source"] = ""
        with self.assertRaises(ReviewError):
            validate_result(candidate("ABC"), bad)


if __name__ == "__main__":
    unittest.main()

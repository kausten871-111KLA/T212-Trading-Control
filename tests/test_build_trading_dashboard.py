import json
import tempfile
import unittest
from pathlib import Path

from scripts.build_trading_dashboard import build_from_state, ledger_record


NOW = "2026-10-02T14:25:00Z"


def write(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


class BuildTradingDashboardTests(unittest.TestCase):
    def test_state_files_build_one_complete_no_order_artifact(self):
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder)
            write(state / "market_snapshot.json", {
                "generated_at": "2026-10-02T14:24:30Z", "environment": "DEMO",
                "live_trading_enabled": False, "orders_submitted": 0,
                "rows": [{"symbol": "AAA", "change_pct": 7.0}],
            })
            write(state / "scanner_latest.json", {
                "generated_at": "2026-10-02T14:24:35Z", "environment": "DEMO",
                "live_trading_enabled": False, "orders_submitted": 0,
                "qualified_count": 1, "shortlist": [{"symbol": "AAA"}], "rejected": [],
            })
            write(state / "candidate_readiness.json", {
                "generated_at": "2026-10-02T14:24:40Z", "environment": "DEMO",
                "live_trading_enabled": False, "orders_submitted": 0,
                "state": "NO_CANDIDATE_READY", "reviewed_count": 0, "candidates": [],
                "broker_snapshot": {
                    "generated_at": "2026-10-02T14:24:45Z", "environment": "DEMO",
                    "live_trading_enabled": False, "orders_submitted": 0,
                    "currency": "GBP", "equity": 1000, "available_cash": 1000,
                    "open_position_count": 0, "pending_order_count": 0,
                    "positions": [], "pending_orders": [],
                },
            })
            write(state / "t212_instrument_diff.json", {
                "generatedAt": "2026-10-02T13:00:00Z", "baselineWasPresent": True,
                "added": [{"ticker": "NEW_US_EQ"}],
            })
            write(state / "broker_fills.json", [{"ticker": "AAA_US_EQ"}])
            write(state / "eod_audit_latest.json", {
                "generated_at": "2026-10-02T14:24:50Z", "environment": "DEMO",
                "live_trading_enabled": False, "orders_submitted": 0,
                "audit": {"counts": {"NEV": 1}, "rows": [{"symbol": "BBB", "audit_code": "NEV"}]},
            })
            result = build_from_state(state, generated_at=NOW)
            self.assertEqual(result["status"], "EVIDENCE_COMPLETE")
            self.assertEqual(result["portfolio"]["state"], "BROKER_VERIFIED")
            self.assertEqual(result["opportunity"]["new_on_t212"][0]["ticker"], "NEW_US_EQ")
            self.assertEqual(result["learning"]["funnel"]["traded"], 0)
            self.assertEqual(result["learning"]["missed_green_audit"]["counts"]["NEV"], 1)
            self.assertEqual(result["safety"]["orders_submitted"], 0)

    def test_missing_state_fails_closed_and_builds_blocked_handoff_record(self):
        with tempfile.TemporaryDirectory() as folder:
            result = build_from_state(Path(folder), generated_at=NOW)
        self.assertEqual(result["status"], "DEGRADED")
        self.assertEqual(result["portfolio"]["state"], "UNKNOWN")
        record = ledger_record(result, Path("trading_dashboard_latest.json"))
        self.assertEqual(record["status"], "BLOCKED")
        self.assertEqual(record["safety"]["environment"], "DEMO")
        self.assertFalse(record["safety"]["order_mutation"])
        self.assertIn("market_snapshot", record["error"]["summary"])

    def test_legacy_fill_rows_require_explicit_broker_verification(self):
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder)
            write(state / "broker_fills.json", [
                {"ticker": "UNVERIFIED_US_EQ"},
                {"ticker": "VERIFIED_US_EQ", "broker_verified": True},
            ])
            result = build_from_state(state, generated_at=NOW)
        self.assertEqual(result["learning"]["funnel"]["traded"], 1)


if __name__ == "__main__":
    unittest.main()

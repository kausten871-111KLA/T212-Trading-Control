import json
import unittest
from pathlib import Path

from openwebui.tools.trading_dashboard_evidence import build_trading_dashboard


NOW = "2026-10-02T14:25:00Z"


def market(at="2026-10-02T14:24:30Z"):
    return {
        "generated_at": at,
        "environment": "DEMO",
        "live_trading_enabled": False,
        "orders_submitted": 0,
        "rows": [
            {"symbol": "AAA", "change_pct": 8.0, "observation_timestamp": at},
            {"symbol": "BBB", "change_pct": 3.0, "observation_timestamp": at},
        ],
    }


def scan(at="2026-10-02T14:24:35Z"):
    return {
        "generated_at": at,
        "environment": "DEMO",
        "live_trading_enabled": False,
        "orders_submitted": 0,
        "qualified_count": 1,
        "shortlist": [{"symbol": "AAA"}],
        "rejected": [{"symbol": "BBB", "reasons": ["SPREAD_LIMIT"]}],
    }


def ready(at="2026-10-02T14:24:40Z", broker_at="2026-10-02T14:24:45Z"):
    return {
        "generated_at": at,
        "environment": "DEMO",
        "live_trading_enabled": False,
        "orders_submitted": 0,
        "state": "READY_FOR_PROPOSAL",
        "reviewed_count": 1,
        "candidates": [{"symbol": "AAA", "decision": "READY_FOR_PROPOSAL", "reasons": []}],
        "broker_snapshot": {
            "generated_at": broker_at,
            "environment": "DEMO",
            "live_trading_enabled": False,
            "orders_submitted": 0,
            "currency": "GBP",
            "equity": 1000.0,
            "available_cash": 600.0,
            "open_position_count": 1,
            "pending_order_count": 0,
            "positions": [{"ticker": "AAA_US_EQ"}],
            "pending_orders": [],
        },
    }


class TradingDashboardEvidenceTests(unittest.TestCase):
    def test_fresh_broker_state_is_visible_and_funnel_is_exact(self):
        result = build_trading_dashboard(
            market_snapshot=market(), scanner=scan(), readiness=ready(), generated_at=NOW
        )
        self.assertEqual(result["portfolio"]["state"], "BROKER_VERIFIED")
        self.assertEqual(result["portfolio"]["equity"], 1000.0)
        self.assertEqual(result["learning"]["funnel"], {
            "actual": 2, "surfaced": 1, "qualified": 1,
            "ready": 1, "traded": 0, "missed_actual_not_surfaced": 1,
        })
        self.assertEqual(result["opportunity"]["top_winners"][0]["symbol"], "AAA")

    def test_stale_broker_values_are_suppressed(self):
        result = build_trading_dashboard(
            market_snapshot=market(), scanner=scan(),
            readiness=ready(broker_at="2026-10-02T14:20:00Z"), generated_at=NOW,
        )
        self.assertEqual(result["portfolio"]["state"], "UNKNOWN")
        self.assertIsNone(result["portfolio"]["equity"])
        self.assertIn("broker", result["degraded_evidence"])

    def test_live_or_mutating_evidence_is_rejected(self):
        unsafe = market()
        unsafe["live_trading_enabled"] = True
        with self.assertRaisesRegex(ValueError, "LIVE trading enabled"):
            build_trading_dashboard(market_snapshot=unsafe, generated_at=NOW)
        mutating = scan()
        mutating["orders_submitted"] = 1
        with self.assertRaisesRegex(ValueError, "order mutation"):
            build_trading_dashboard(scanner=mutating, generated_at=NOW)

    def test_rejections_map_to_failure_taxonomy(self):
        result = build_trading_dashboard(
            market_snapshot=market(), scanner=scan(), readiness=ready(), generated_at=NOW
        )
        self.assertEqual(result["learning"]["rejection_reasons"]["SPREAD_LIMIT"], 1)
        self.assertEqual(result["learning"]["failure_taxonomy"]["MARKET"], 1)

    def test_role_configuration_does_not_claim_persistent_agents(self):
        bindings = json.loads(
            (Path(__file__).parents[1] / "webui-control" / "t212-agent-bindings.json")
            .read_text(encoding="utf-8")
        )
        result = build_trading_dashboard(agent_bindings=bindings, generated_at=NOW)
        self.assertEqual(len(result["agent_roles"]), 4)
        self.assertFalse(result["runtime_agents_proven"])
        self.assertTrue(all(not row["persistent_agent"] for row in result["agent_roles"]))
        self.assertTrue(all(not row["broker_write_authority"] for row in result["agent_roles"]))

    def test_missed_green_audit_is_reported_without_auto_applying_thresholds(self):
        result = build_trading_dashboard(
            eod_audit={
                "environment": "DEMO",
                "generated_at": "2026-10-02T14:24:50Z",
                "orders_submitted": 0,
                "audit": {"counts": {"NEV": 1}, "rows": [{"symbol": "BBB"}]},
            },
            generated_at=NOW,
        )
        audit = result["learning"]["missed_green_audit"]
        self.assertEqual(audit["state"], "VERIFIED_ARTIFACT")
        self.assertEqual(audit["counts"]["NEV"], 1)
        self.assertFalse(audit["threshold_changes_auto_applied"])


if __name__ == "__main__":
    unittest.main()

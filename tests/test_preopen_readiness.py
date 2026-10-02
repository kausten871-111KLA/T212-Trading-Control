import unittest

from scripts.build_preopen_readiness import build_gate


NOW = "2026-10-02T14:25:00Z"


def complete_inputs():
    runtime = {
        "generated_at": "2026-10-02T14:24:30Z",
        "artifacts": {"instrument_cache": {"present": True, "age_seconds": 60}},
        "components": [
            {"id": "discovery-adapter", "deployed": True, "running": False},
            {"id": "discovery-worker", "deployed": True, "running": True},
        ],
    }
    dashboard = {
        "generated_at": "2026-10-02T14:24:40Z",
        "safety": {"environment": "DEMO", "live_trading": False, "order_mutation": False, "orders_submitted": 0},
        "freshness": {"broker": {"state": "FRESH"}, "market_snapshot": {"state": "FRESH"}},
        "portfolio": {"state": "BROKER_VERIFIED", "equity": 1000, "available_cash": 900, "open_position_count": 0, "pending_order_count": 0},
        "opportunity": {"actual_market_rows": 20, "top_winners": [{"symbol": "AAA"}], "new_on_t212": [], "new_on_t212_baseline_verified": True},
        "learning": {"missed_green_audit": {"state": "VERIFIED_ARTIFACT", "rows": [{"symbol": "BBB"}], "counts": {"NEV": 1}}},
    }
    keys = [
        "instrument_mapping", "relative_volume", "catalyst_news", "liquidity_spread",
        "cause_effect", "methodology_risk", "demo_order_cycle", "position_lifecycle",
        "equity_curve", "automation_owner", "session_authority",
    ]
    acceptance = {
        "generated_at": "2026-10-02T14:00:00Z", "environment": "DEMO",
        "live_trading_enabled": False,
        "checks": {key: {"status": "PASS", "evidence": [f"{key}=verified"]} for key in keys},
    }
    return runtime, dashboard, acceptance


class PreopenReadinessTests(unittest.TestCase):
    def test_missing_evidence_is_no_go_not_pass(self):
        result = build_gate(None, None, None, generated_at=NOW)
        self.assertEqual(result["decision"], "NO_GO")
        self.assertEqual(result["counts"]["PASS"], 0)
        self.assertGreater(result["counts"]["MISSING"], 0)
        self.assertEqual(result["safety"]["orders_submitted_by_gate"], 0)

    def test_complete_current_evidence_is_go(self):
        result = build_gate(*complete_inputs(), generated_at=NOW)
        self.assertEqual(result["decision"], "GO")
        self.assertEqual(result["counts"]["FAIL"], 0)
        self.assertEqual(result["counts"]["MISSING"], 0)

    def test_live_enabled_dashboard_is_hard_fail(self):
        runtime, dashboard, acceptance = complete_inputs()
        dashboard["safety"]["live_trading"] = True
        result = build_gate(runtime, dashboard, acceptance, generated_at=NOW)
        safety = next(row for row in result["checks"] if row["id"] == "demo_safety")
        self.assertEqual(safety["status"], "FAIL")
        self.assertEqual(result["decision"], "NO_GO")

    def test_stale_runtime_and_acceptance_evidence_fail(self):
        runtime, dashboard, acceptance = complete_inputs()
        runtime["generated_at"] = "2026-10-02T13:00:00Z"
        acceptance["generated_at"] = "2026-09-30T14:00:00Z"
        result = build_gate(runtime, dashboard, acceptance, generated_at=NOW)
        self.assertEqual(result["decision"], "NO_GO")
        self.assertGreater(result["counts"]["FAIL"], 0)

    def test_empty_new_list_requires_verified_baseline(self):
        runtime, dashboard, acceptance = complete_inputs()
        dashboard["opportunity"]["new_on_t212_baseline_verified"] = False
        result = build_gate(runtime, dashboard, acceptance, generated_at=NOW)
        check = next(row for row in result["checks"] if row["id"] == "new_on_t212")
        self.assertEqual(check["status"], "MISSING")
        self.assertEqual(result["decision"], "NO_GO")


if __name__ == "__main__":
    unittest.main()

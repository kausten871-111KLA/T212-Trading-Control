import unittest
from datetime import datetime, timezone

from openwebui.tools.t212_risk_gate import evaluate
from openwebui.tools.trading_state_machine import TradingStateError, validate_transition


class TradingControlTests(unittest.TestCase):
    def proposal(self):
        return {
            "proposal_id": "p-1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "entry_range": {"low": 9.9, "high": 10.1},
            "profit_targets": [10.8],
            "risk_stop": 9.8,
            "quantity": 5,
            "intended_exposure": 50,
            "spread": {"pct_midpoint": 1.0},
            "safety": {
                "environment": "DEMO",
                "live_trading": False,
                "order_mutation_authorized": False,
            },
        }

    def portfolio(self):
        return {
            "broker_verified": True,
            "equity": 500,
            "available_cash": 500,
            "pending_commitments": 0,
            "candidate_reservations": 0,
            "open_position_count": 0,
            "aggregate_open_risk": 0,
            "daily_loss": 0,
            "starting_daily_equity": 500,
            "weekly_loss": 0,
            "starting_weekly_equity": 500,
            "high_water_equity": 500,
        }

    def test_risk_gate_passes_bounded_demo_proposal(self):
        result = evaluate(self.proposal(), self.portfolio())
        self.assertEqual(result["decision"], "PASS")
        self.assertEqual(result["safety"]["environment"], "DEMO")
        self.assertFalse(result["safety"]["live_trading"])

    def test_risk_gate_rejects_unverified_broker_state(self):
        portfolio = self.portfolio()
        portfolio["broker_verified"] = False
        result = evaluate(self.proposal(), portfolio)
        self.assertEqual(result["decision"], "REJECT")
        self.assertIn("BROKER_STATE_UNVERIFIED", result["reasons"])

    def test_execution_transition_requires_approval_and_authorization(self):
        record = self.proposal()
        record["approval_state"] = "PENDING"
        with self.assertRaises(TradingStateError):
            validate_transition("HUMAN_APPROVAL", "DEMO_EXECUTION", record)

        record["approval_state"] = "APPROVED"
        record["safety"]["order_mutation_authorized"] = True
        validate_transition("HUMAN_APPROVAL", "DEMO_EXECUTION", record)

    def test_broker_verification_requires_response_evidence(self):
        record = self.proposal()
        record["broker_order_id"] = "demo-id"
        with self.assertRaises(TradingStateError):
            validate_transition("DEMO_EXECUTION", "BROKER_VERIFICATION", record)


if __name__ == "__main__":
    unittest.main()

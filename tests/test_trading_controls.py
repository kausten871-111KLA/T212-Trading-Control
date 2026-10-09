import unittest
import copy
import math
from datetime import datetime, timezone

from openwebui.tools.t212_risk_gate import evaluate, load_controls, position_count_limit, RiskGateError
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
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "environment": "DEMO",
            "live_trading_enabled": False,
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

    def test_risk_gate_rejects_stale_or_unsafe_broker_state(self):
        portfolio = self.portfolio()
        portfolio["generated_at"] = "2026-01-01T00:00:00Z"
        result = evaluate(
            self.proposal(),
            portfolio,
            now=datetime(2026, 1, 1, 0, 3, tzinfo=timezone.utc),
        )
        self.assertEqual(result["decision"], "REJECT")
        self.assertIn("BROKER_STATE_STALE", result["reasons"])

        portfolio = self.portfolio()
        portfolio["live_trading_enabled"] = True
        result = evaluate(self.proposal(), portfolio)
        self.assertEqual(result["decision"], "REJECT")
        self.assertIn("BROKER_ENVIRONMENT_UNSAFE", result["reasons"])

    def test_approved_demo_count_relaxation_preserves_other_risk_gates(self):
        portfolio = self.portfolio();portfolio['open_position_count']=12
        self.assertEqual(evaluate(self.proposal(),portfolio)['decision'],'PASS')
        for field,value,reason in [('aggregate_open_risk',9,'AGGREGATE_OPEN_RISK_LIMIT'),('daily_loss',6,'DAILY_LOSS_STOP'),('weekly_loss',12,'WEEKLY_LOSS_STOP'),('available_cash',0,'AVAILABLE_CASH_LIMIT')]:
            with self.subTest(field=field):
                state=copy.deepcopy(portfolio);state[field]=value
                self.assertIn(reason,evaluate(self.proposal(),state)['reasons'])
        proposal=self.proposal();proposal['intended_exposure']=76
        self.assertIn('POSITION_VALUE_LIMIT',evaluate(proposal,portfolio)['reasons'])
        proposal=self.proposal();proposal['quantity']=100
        self.assertIn('PLANNED_LOSS_LIMIT',evaluate(proposal,portfolio)['reasons'])

    def test_legacy_position_cap_remains_supported(self):
        controls=load_controls();controls['controls']['max_concurrent_positions']=3
        portfolio=self.portfolio();portfolio['open_position_count']=3
        self.assertIn('MAX_CONCURRENT_POSITIONS',evaluate(self.proposal(),portfolio,controls=controls)['reasons'])

    def test_count_relaxation_requires_explicit_demo_authorization(self):
        for mutate in [lambda c:c.pop('position_count_policy'),lambda c:c.update(environment='LIVE'),lambda c:c['position_count_policy'].update(approved=False),lambda c:c['position_count_policy'].pop('approval_reference'),lambda c:c['position_count_policy'].update(other_risk_limits_unchanged=False),lambda c:c['controls'].pop('max_concurrent_positions')]:
            controls=load_controls();mutate(controls)
            with self.assertRaises(RiskGateError):position_count_limit(controls)

    def test_nonfinite_inputs_cannot_bypass_risk_limits(self):
        for value in [float('nan'),float('inf'),True]:
            proposal=self.proposal();proposal['intended_exposure']=value
            with self.assertRaises(RiskGateError):evaluate(proposal,self.portfolio())

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

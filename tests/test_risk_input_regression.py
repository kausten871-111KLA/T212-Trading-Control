import copy
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('risk',ROOT/'openwebui/tools/t212_risk_gate.py')
R=importlib.util.module_from_spec(spec);spec.loader.exec_module(R)


class RiskInputs(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,10,11,14,tzinfo=timezone.utc)
        self.proposal=dict(proposal_id='intent-1',generated_at=self.now.isoformat(),entry_range={'low':9.9,'high':10.1},profit_targets=[10.8],risk_stop=9.8,quantity=5,intended_exposure=50.5,spread={'pct_midpoint':1},safety={'environment':'DEMO','live_trading':False})
        self.portfolio=dict(broker_verified=True,generated_at=self.now.isoformat(),environment='DEMO',live_trading_enabled=False,equity=500,available_cash=500,pending_commitments=0,candidate_reservations=0,open_position_count=12,aggregate_open_risk=0,daily_loss=0,starting_daily_equity=500,weekly_loss=0,starting_weekly_equity=500,high_water_equity=500)

    def evaluate(self,p=None,s=None):
        return R.evaluate(p or self.proposal,s or self.portfolio,now=self.now)

    def test_bounded_proposal_passes_with_approved_count_relaxation(self):
        result=self.evaluate();self.assertEqual(result['decision'],'PASS')
        self.assertEqual(result['metrics']['planned_loss'],1.5)

    def test_underdeclared_exposure_rejected(self):
        self.proposal['intended_exposure']=1
        with self.assertRaises(R.RiskGateError):self.evaluate()

    def test_future_broker_timestamp_rejected(self):
        self.portfolio['generated_at']=(self.now+timedelta(seconds=1)).isoformat()
        self.assertIn('BROKER_STATE_FUTURE',self.evaluate()['reasons'])

    def test_future_proposal_timestamp_rejected(self):
        self.proposal['generated_at']=(self.now+timedelta(seconds=1)).isoformat()
        self.assertIn('PROPOSAL_FUTURE',self.evaluate()['reasons'])

    def test_missing_portfolio_metrics_never_default_to_zero(self):
        for field in ('pending_commitments','candidate_reservations','open_position_count','aggregate_open_risk','daily_loss','starting_daily_equity','weekly_loss','starting_weekly_equity','high_water_equity'):
            with self.subTest(field=field):
                state=copy.deepcopy(self.portfolio);state.pop(field)
                with self.assertRaises(R.RiskGateError):self.evaluate(s=state)

    def test_negative_nonfinite_and_fractional_state_rejected(self):
        for field,value in [('aggregate_open_risk',-10),('daily_loss',float('nan')),('pending_commitments',float('inf')),('candidate_reservations',True),('open_position_count',1.5)]:
            with self.subTest(field=field):
                state=copy.deepcopy(self.portfolio);state[field]=value
                with self.assertRaises(R.RiskGateError):self.evaluate(s=state)

    def test_retained_loss_exposure_cash_spread_gates(self):
        for field,value,reason in [('available_cash',0,'AVAILABLE_CASH_LIMIT'),('aggregate_open_risk',9,'AGGREGATE_OPEN_RISK_LIMIT'),('daily_loss',6,'DAILY_LOSS_STOP'),('weekly_loss',12,'WEEKLY_LOSS_STOP'),('high_water_equity',550,'EXPERIMENT_DRAWDOWN_STOP')]:
            with self.subTest(field=field):
                state=copy.deepcopy(self.portfolio);state[field]=value
                self.assertIn(reason,self.evaluate(s=state)['reasons'])
        self.proposal['spread']['pct_midpoint']=3
        self.assertIn('SPREAD_LIMIT',self.evaluate()['reasons'])
        self.proposal['intended_exposure']=76
        self.assertIn('POSITION_VALUE_LIMIT',self.evaluate()['reasons'])

    def test_strategy_flags_and_sell_are_not_entry_admission(self):
        for field in ('shorting','leverage','cfds','averaging_down','martingale','revenge_or_loss_chasing'):
            with self.subTest(field=field):
                p=copy.deepcopy(self.proposal);p[field]=True
                with self.assertRaises(R.RiskGateError):self.evaluate(p=p)
        self.proposal['side']='SELL'
        with self.assertRaises(R.RiskGateError):self.evaluate()

    def test_stale_broker_and_live_environment_rejected(self):
        self.portfolio['generated_at']=(self.now-timedelta(seconds=121)).isoformat()
        self.assertIn('BROKER_STATE_STALE',self.evaluate()['reasons'])
        self.portfolio['live_trading_enabled']=True
        self.assertIn('BROKER_ENVIRONMENT_UNSAFE',self.evaluate()['reasons'])

    def test_negative_friction_spread_partial_prices_and_naive_clock_rejected(self):
        for changes in ({'spread':{'pct_midpoint':-1}}, {'expected_friction_pct_planned_risk':-1}, {'current_reference_price':10}, {'proposal_reference_price':0,'current_reference_price':10}):
            with self.subTest(changes=changes):
                proposal=copy.deepcopy(self.proposal);proposal.update(changes)
                with self.assertRaises(R.RiskGateError):self.evaluate(p=proposal)
        with self.assertRaises(R.RiskGateError):
            R.evaluate(self.proposal,self.portfolio,now=self.now.replace(tzinfo=None))


if __name__=='__main__':unittest.main(verbosity=2)

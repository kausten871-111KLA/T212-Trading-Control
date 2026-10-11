import copy
from datetime import datetime,timezone,timedelta
import sys
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from openwebui.tools.risk_admission import admit_request
from openwebui.tools.t212_risk_gate import RiskGateError,load_controls


class Binding(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,10,11,14,tzinfo=timezone.utc)
        self.body={'ticker':'ACME_US_EQ','quantity':5,'limitPrice':10,'timeValidity':'DAY'}
        self.path='/equity/orders/limit'
        self.p=dict(proposal_id='id-1',generated_at=self.now.isoformat(),entry_range={'low':9.9,'high':10.1},profit_targets=[10.8],risk_stop=9.8,quantity=5,intended_exposure=50.5,spread={'pct_midpoint':1},safety={'environment':'DEMO','live_trading':False},execution={'method':'POST','path':self.path,'body':copy.deepcopy(self.body)},risk_currency='GBP',instrument_currency='GBP',instrument_to_account_fx=1,fx_verified=True,fx_generated_at=self.now.isoformat())
        self.s=dict(account_id='demo-account',account_currency='GBP',broker_verified=True,generated_at=self.now.isoformat(),environment='DEMO',live_trading_enabled=False,equity=500,available_cash=500,pending_commitments=0,candidate_reservations=0,open_position_count=12,aggregate_open_risk=0,daily_loss=0,starting_daily_equity=500,weekly_loss=0,starting_weekly_equity=500,high_water_equity=500)

    def run_gate(self):
        return admit_request('id-1','POST',self.path,self.body,self.p,self.s,expected_account_id='demo-account',controls=load_controls(),now=self.now)

    def test_exact_valid_request_passes_pure_gate(self):
        result=self.run_gate();self.assertEqual(result['decision'],'PASS');self.assertEqual(result['execution']['body'],self.body)

    def test_payload_changes_cannot_reuse_proposal(self):
        for field,value in [('ticker','OTHER_US_EQ'),('quantity',6),('limitPrice',11),('timeValidity','GOOD_TILL_CANCEL')]:
            with self.subTest(field=field):
                old=self.body[field];self.body[field]=value
                with self.assertRaises(RiskGateError):self.run_gate()
                self.body[field]=old

    def test_account_and_intent_identity_must_match(self):
        self.s['account_id']='other'
        with self.assertRaises(RiskGateError):self.run_gate()
        self.s['account_id']='demo-account';self.p['proposal_id']='other'
        with self.assertRaises(RiskGateError):self.run_gate()

    def test_fx_and_currency_inputs_required(self):
        for field,value in [('risk_currency','USD'),('instrument_to_account_fx',float('nan')),('fx_verified',False),('fx_generated_at',(self.now-timedelta(seconds=121)).isoformat()),('fx_generated_at',(self.now+timedelta(seconds=1)).isoformat())]:
            with self.subTest(field=field):
                old=self.p[field];self.p[field]=value
                with self.assertRaises(RiskGateError):self.run_gate()
                self.p[field]=old

    def test_bound_payload_cannot_understate_risk_quantity_or_price(self):
        self.p['quantity']=1
        with self.assertRaises(RiskGateError):self.run_gate()
        self.p['quantity']=5;self.p['entry_range']['high']=9.95
        with self.assertRaises(RiskGateError):self.run_gate()

    def test_risk_rejection_is_not_admission(self):
        self.s['available_cash']=0
        with self.assertRaises(RiskGateError):self.run_gate()


if __name__=='__main__':unittest.main(verbosity=2)

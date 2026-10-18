import json
import tempfile
import unittest
from pathlib import Path
from runtime.deepseek.service import migrate
from runtime.deepseek.orchestrator import StateDB
from runtime.deepseek.intent_recovery import IntentReconciler

class Gateway:
    def __init__(self, result): self.result, self.calls = result, []
    def reconcile(self, intent_id): self.calls.append(intent_id); return self.result
    def place_market(self, *a): raise AssertionError('Recovery must never submit')

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)/'state.db'
        migrate(self.path)
        self.db = StateDB(str(self.path))
        self.proposal = dict(intent_id='intent-test',ticker='TEST_US_EQ',side='BUY',quantity=1)
        self.db.prepare_intent(self.proposal)
        self.event = self.db.emit('EXECUTE_ORDER', self.proposal)
        self.db.conn.execute("UPDATE event_queue SET status='awaiting_verification' WHERE id=?",(self.event,))
        self.db.conn.commit()
    def tearDown(self): self.db.conn.close(); self.tmp.cleanup()
    def test_unknown_survives_restart_then_reconciles_without_submit(self):
        gateway = Gateway({'status':'UNKNOWN'})
        self.assertEqual(IntentReconciler(self.db,gateway).run_once()['unresolved'],1)
        self.db.conn.close(); self.db = StateDB(str(self.path))
        gateway.result = {'status':'FILLED','broker_order_id':123,'receipt':{'status':'FILLED'},'filled_qty':1}
        self.assertEqual(IntentReconciler(self.db,gateway).run_once()['reconciled'],1)
        self.assertEqual(IntentReconciler(self.db,gateway).run_once()['reconciled'],0)
        self.assertEqual(gateway.calls,['intent-test','intent-test'])
    def test_missing_identity_stays_unresolved(self):
        gateway = Gateway({'status':'FILLED'})
        self.assertEqual(IntentReconciler(self.db,gateway).run_once()['unresolved'],1)
    def test_missing_intent_does_not_contact_gateway(self):
        self.db.conn.execute('DELETE FROM intent'); self.db.conn.commit()
        gateway=Gateway({'status':'UNKNOWN'})
        self.assertEqual(IntentReconciler(self.db,gateway).run_once()['failed'],1)
        self.assertEqual(gateway.calls,[])
    def test_partial_fill_remains_pending_until_terminal(self):
        gateway=Gateway({'status':'PARTIALLY_FILLED','broker_order_id':123,'filled_qty':0.5})
        self.assertEqual(IntentReconciler(self.db,gateway).run_once()['unresolved'],1)
        row=self.db.conn.execute('SELECT status FROM event_queue WHERE id=?',(self.event,)).fetchone()
        self.assertEqual(row[0],'awaiting_verification')
        gateway.result={'status':'FILLED','broker_order_id':123,'filled_qty':1}
        self.assertEqual(IntentReconciler(self.db,gateway).run_once()['reconciled'],1)

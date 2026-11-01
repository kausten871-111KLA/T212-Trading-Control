"""Cross-check staged controller and recovery seams against the 20-table schema."""
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from runtime.deepseek.controller_phase_bridge import ControllerPhaseBridge, PHASE_BY_AUTOMATION
from runtime.deepseek.controller_dispatch import ControllerPhaseDispatcher
from runtime.deepseek.controller_ack import ControllerAcknowledgements
from runtime.deepseek.recovery_audit import PreJournalRecoveryAudit

SCHEMA = Path(__file__).resolve().parents[1] / 'runtime/deepseek/schema.sql'


class DB:
    def __init__(self, path):
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('PRAGMA busy_timeout=5000')
        self.conn.execute('PRAGMA foreign_keys=ON')
        self.conn.executescript(SCHEMA.read_text())
        self.conn.execute('ALTER TABLE event_queue ADD COLUMN claim_token TEXT')
        self.conn.commit()


class IntegratedMockLifecycle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.db = DB(str(Path(self.tmp.name) / 'state.sqlite'))
        self.addCleanup(self.db.conn.close)
        auth = lambda principal, aid: principal == 'authenticated-host' and aid in PHASE_BY_AUTOMATION
        self.bridge = ControllerPhaseBridge(self.db, auth)
        self.dispatch = ControllerPhaseDispatcher(self.db)
        self.ack = ControllerAcknowledgements(self.db, auth)
        self.dispatch.install_schema(); self.ack.install_schema()
        self.audit = PreJournalRecoveryAudit(self.db)

    def test_phase_dispatch_ack_and_independent_recovery(self):
        automation = next(iter(PHASE_BY_AUTOMATION))
        event, created = self.bridge.enqueue(automation_id=automation, market_date='2026-10-19',
                                             principal='authenticated-host')
        self.assertTrue(created)
        self.db.conn.execute(
            "UPDATE event_queue SET status='claimed',worker_id='controller-worker',"
            "claim_token='lease-token',lease_expires_at=9999999999 WHERE id=?", (event,)
        ); self.db.conn.commit()
        instruction, created = self.dispatch.dispatch_claim(
            {'id': event, 'worker_id': 'controller-worker', 'claim_token': 'lease-token'})
        self.assertTrue(created)
        receipt, created = self.ack.acknowledge(
            instruction_id=instruction, principal='authenticated-host',
            outcome={'processing': 'accepted_for_controller', 'decision_ref': 'mock-1'})
        self.assertTrue(created)
        self.assertEqual(self.bridge.enqueue(automation_id=automation, market_date='2026-10-19',
                                             principal='authenticated-host'), (event, False))
        self.assertEqual(self.ack.status(instruction_id=instruction,
                                         principal='authenticated-host')['receipt_id'], receipt)
        self.db.conn.execute(
            "INSERT INTO intent(id,ticker,side,quantity,order_type,status,created_at) "
            "VALUES('mock-1','ACME_US_EQ','BUY',1,'MARKET','DISPATCHING',100)"
        ); self.db.conn.commit()
        self.assertEqual(self.audit.scan(now=500), ['mock-1'])
        self.assertEqual(self.audit.scan(now=800), [])
        self.assertEqual(self.db.conn.execute('SELECT count(*) FROM "order"').fetchone()[0], 0)
        self.assertEqual(self.db.conn.execute('SELECT count(*) FROM controller_instruction').fetchone()[0], 1)
        self.assertEqual(self.db.conn.execute('SELECT count(*) FROM recovery_record').fetchone()[0], 1)

    def test_unauthorized_phase_never_generates_instruction(self):
        automation = next(iter(PHASE_BY_AUTOMATION))
        with self.assertRaises(PermissionError):
            self.bridge.enqueue(automation_id=automation, market_date='2026-10-19',
                                principal='untrusted')
        self.assertEqual(self.db.conn.execute('SELECT count(*) FROM controller_instruction').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()

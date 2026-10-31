import concurrent.futures
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from runtime.deepseek.recovery_audit import PreJournalRecoveryAudit

SCHEMA = Path(__file__).resolve().parents[1] / 'runtime/deepseek/schema.sql'


class DB:
    def __init__(self, path):
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False, timeout=5)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('PRAGMA journal_mode=WAL')
        self.conn.execute('PRAGMA foreign_keys=ON')
        self.conn.execute('PRAGMA busy_timeout=5000')
        self.conn.executescript(SCHEMA.read_text())


class RecoveryAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / 'state.sqlite')
        self.db = DB(self.path)
        self.addCleanup(self.db.conn.close)
        self.audit = PreJournalRecoveryAudit(self.db)

    def intent(self, key='decision-1', created=100, status='DISPATCHING'):
        self.db.conn.execute(
            "INSERT INTO intent(id,ticker,side,quantity,order_type,status,created_at) "
            "VALUES(?, 'ACME_US_EQ', 'BUY', 1, 'MARKET', ?, ?)",
            (key, status, created),
        )
        self.db.conn.commit()
        return key

    def test_stale_without_receipt_is_flagged_once(self):
        self.intent()
        self.assertEqual(self.audit.scan(now=500), ['decision-1'])
        self.assertEqual(self.audit.scan(now=900), [])
        self.assertEqual(len(self.audit.pending()), 1)
        self.assertEqual(self.audit.pending()[0]['state'], 'AWAITING_BROKER_VERIFICATION')

    def test_recent_intent_not_flagged(self):
        self.intent(created=400)
        self.assertEqual(self.audit.scan(now=500), [])

    def test_broker_order_receipt_prevents_flag(self):
        self.intent()
        self.db.conn.execute(
            'INSERT INTO "order"(broker_order_id,intent_id,ticker,side,quantity,order_type,status,created_at) '
            "VALUES(42,'decision-1','ACME_US_EQ','BUY',1,'MARKET','PENDING',150)"
        )
        self.db.conn.commit()
        self.assertEqual(self.audit.scan(now=500), [])

    def test_existing_unresolved_receipt_prevents_duplicate(self):
        self.intent()
        self.db.conn.execute(
            "INSERT INTO recovery_record(intent_id,recovery_type,state,created_at) "
            "VALUES('decision-1','BROKER_ID_UNRESOLVED','UNKNOWN',200)"
        )
        self.db.conn.commit()
        self.assertEqual(self.audit.scan(now=500), [])

    def test_active_claim_not_flagged(self):
        self.intent()
        self.db.conn.execute(
            "INSERT INTO event_queue(event_type,payload,created_at,status,lease_expires_at) "
            "VALUES('EXECUTE_ORDER',?,100,'claimed',600)",
            (json.dumps({'intent_id': 'decision-1'}),)
        )
        self.db.conn.commit()
        self.assertEqual(self.audit.scan(now=500), [])
        self.assertEqual(self.audit.scan(now=700), ['decision-1'])

    def test_non_dispatching_intent_not_flagged(self):
        self.intent(status='CONFIRMED')
        self.assertEqual(self.audit.scan(now=500), [])

    def test_concurrent_two_connections_insert_once(self):
        self.intent()
        other = DB(self.path)
        self.addCleanup(other.conn.close)
        barrier = threading.Barrier(2)
        def scan(audit):
            barrier.wait()
            return audit.scan(now=500)
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            a = pool.submit(scan, self.audit)
            b = pool.submit(scan, PreJournalRecoveryAudit(other))
            self.assertEqual(len(a.result()) + len(b.result()), 1)
        self.assertEqual(len(self.audit.pending()), 1)

    def test_restart_preserves_audit(self):
        self.intent()
        self.audit.scan(now=500)
        other = DB(self.path)
        self.addCleanup(other.conn.close)
        self.assertEqual(PreJournalRecoveryAudit(other).scan(now=800), [])
        self.assertEqual(len(PreJournalRecoveryAudit(other).pending()), 1)

    def test_no_schema_change_and_no_broker_orders(self):
        self.intent()
        before = self.db.conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchone()[0]
        self.audit.scan(now=500)
        after = self.db.conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchone()[0]
        self.assertEqual((before, after), (20, 20))
        self.assertEqual(self.db.conn.execute('SELECT count(*) FROM "order"').fetchone()[0], 0)
        self.assertEqual(self.db.conn.execute('SELECT status FROM intent').fetchone()[0], 'DISPATCHING')

    def test_invalid_diagnostic_age_rejected(self):
        self.intent()
        with self.assertRaises(ValueError):
            self.audit.scan(now=500, minimum_age_seconds=-1)
        with self.assertRaises(ValueError):
            self.audit.scan(now=float('nan'))


if __name__ == '__main__':
    unittest.main()

import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from runtime.deepseek.controller_phase_bridge import ControllerPhaseBridge, PHASE_BY_AUTOMATION
from runtime.deepseek.controller_dispatch import ControllerPhaseDispatcher

OPEN, MIDDAY, CLOSE = tuple(PHASE_BY_AUTOMATION)

class DB:
    def __init__(self, path):
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('PRAGMA busy_timeout=5000')
        self.conn.execute('PRAGMA journal_mode=WAL')
        self.conn.execute('PRAGMA foreign_keys=ON')
        self.conn.executescript(Path('runtime/deepseek/schema.sql').read_text())
        self.conn.execute('ALTER TABLE event_queue ADD COLUMN claim_token TEXT')
        self.conn.commit()

class ControllerDispatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = DB(str(Path(self.tmp.name)/'state.db'))
        self.addCleanup(self.db.conn.close)
        self.bridge = ControllerPhaseBridge(self.db, lambda p, a: p == 'host')
        self.dispatcher = ControllerPhaseDispatcher(self.db)
        self.dispatcher.install_schema()

    def claim(self, automation=OPEN, date='2026-10-19', token='first', worker='controller-1'):
        event_id, _ = self.bridge.enqueue(automation_id=automation, market_date=date, principal='host')
        self.db.conn.execute("UPDATE event_queue SET status='claimed',worker_id=?,claim_token=?,lease_expires_at=9999999999 WHERE id=?",(worker,token,event_id))
        self.db.conn.commit()
        return {'id':event_id,'worker_id':worker,'claim_token':token}

    def test_dispatch_creates_instruction_and_marks_done(self):
        ev = self.claim()
        instruction, created = self.dispatcher.dispatch_claim(ev)
        self.assertTrue(created)
        self.assertEqual(self.db.conn.execute('SELECT status FROM event_queue WHERE id=?',(ev['id'],)).fetchone()[0], 'done')
        row=self.db.conn.execute('SELECT instruction_type,payload FROM controller_instruction WHERE id=?',(instruction,)).fetchone()
        self.assertEqual(row['instruction_type'],'PHASE_EVENT')
        self.assertIn('MARKET_OPEN',row['payload'])

    def test_replay_does_not_duplicate_instruction(self):
        ev=self.claim(); self.dispatcher.dispatch_claim(ev)
        self.assertIsNone(self.dispatcher.dispatch_claim(ev))
        self.assertEqual(self.db.conn.execute('SELECT count(*) FROM controller_instruction').fetchone()[0],1)

    def test_stale_worker_token_rejected(self):
        ev=self.claim()
        self.assertIsNone(self.dispatcher.dispatch_claim({**ev,'claim_token':'wrong'}))
        self.assertEqual(self.db.conn.execute('SELECT count(*) FROM controller_instruction').fetchone()[0],0)

    def test_expired_lease_rejected(self):
        ev=self.claim()
        self.db.conn.execute('UPDATE event_queue SET lease_expires_at=1 WHERE id=?',(ev['id'],)); self.db.conn.commit()
        self.assertIsNone(self.dispatcher.dispatch_claim(ev))

    def test_three_phases_create_three_instructions(self):
        for a in (OPEN,MIDDAY,CLOSE): self.dispatcher.dispatch_claim(self.claim(automation=a))
        self.assertEqual(self.db.conn.execute('SELECT count(*) FROM controller_instruction').fetchone()[0],3)

    def test_wrong_type_fails_and_rolls_back(self):
        ev=self.claim()
        self.db.conn.execute("UPDATE event_queue SET event_type='EXECUTE_ORDER' WHERE id=?",(ev['id'],));self.db.conn.commit()
        with self.assertRaises(ValueError):self.dispatcher.dispatch_claim(ev)
        self.assertEqual(self.db.conn.execute('SELECT count(*) FROM controller_instruction').fetchone()[0],0)

    def test_mismatched_phase_payload_fails(self):
        ev=self.claim()
        self.db.conn.execute("UPDATE event_queue SET payload='{}' WHERE id=?",(ev['id'],));self.db.conn.commit()
        with self.assertRaises(ValueError):self.dispatcher.dispatch_claim(ev)
        self.assertEqual(self.db.conn.execute('SELECT count(*) FROM controller_instruction').fetchone()[0],0)

    def test_missing_migration_fails_closed(self):
        ev=self.claim()
        self.db.conn.execute('DROP INDEX idx_ctl_result_phase_event');self.db.conn.commit()
        with self.assertRaises(RuntimeError):self.dispatcher.dispatch_claim(ev)
        self.assertEqual(self.db.conn.execute('SELECT count(*) FROM controller_instruction').fetchone()[0],0)

    def test_duplicate_receipt_index_rejects(self):
        ev=self.claim()
        instruction,_=self.dispatcher.dispatch_claim(ev)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.conn.execute("INSERT INTO controller_result(controller_instruction_id,event_id,kind,payload,created_at) VALUES(?,?,'PHASE_DISPATCH','{}',0)",(instruction,ev['id']))
        self.db.conn.rollback()

    def test_atomic_rollback_if_receipt_insert_fails(self):
        ev = self.claim()
        self.db.conn.execute("CREATE TRIGGER fail_receipt BEFORE INSERT ON controller_result "
                             "BEGIN SELECT RAISE(FAIL, 'synthetic journal failure'); END")
        self.db.conn.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            self.dispatcher.dispatch_claim(ev)
        self.assertEqual(self.db.conn.execute('SELECT count(*) FROM controller_instruction').fetchone()[0], 0)
        self.assertEqual(self.db.conn.execute('SELECT status FROM event_queue WHERE id=?', (ev['id'],)).fetchone()[0], 'claimed')

    def test_schema_migration_does_not_add_tables(self):
        count = self.db.conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchone()[0]
        self.assertEqual(count, 20)
        self.dispatcher.install_schema()
        self.assertEqual(self.db.conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchone()[0], 20)

    def test_old_lease_cannot_finish_new_claim(self):
        ev=self.claim(); self.db.conn.execute('UPDATE event_queue SET claim_token=? WHERE id=?',('new',ev['id']));self.db.conn.commit()
        self.assertIsNone(self.dispatcher.dispatch_claim(ev))
        self.assertTrue(self.dispatcher.dispatch_claim({**ev,'claim_token':'new'})[1])

if __name__=='__main__':unittest.main()

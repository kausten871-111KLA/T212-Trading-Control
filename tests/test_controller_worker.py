"""Focused mock integration of worker with the supplied 20-table schema."""
import sqlite3
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path

from runtime.deepseek.controller_phase_bridge import ControllerPhaseBridge, PHASE_BY_AUTOMATION
from runtime.deepseek.controller_worker import ControllerPhaseWorker
from runtime.deepseek.worker_supervisor import WorkerSupervisor

SCHEMA = Path(__file__).resolve().parents[1] / 'runtime/deepseek/schema.sql'


class FakeStateDB:
    """Implements the PR17 StateDB queue surface with a real temporary SQLite DB."""
    def __init__(self, path):
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('PRAGMA busy_timeout=5000')
        self.conn.executescript(SCHEMA.read_text())
        self.conn.execute('ALTER TABLE event_queue ADD COLUMN claim_token TEXT')
        self.conn.commit()

    def requeue_dead(self):
        with self.lock:
            now = time.time()
            cur = self.conn.execute(
                "UPDATE event_queue SET status=CASE WHEN attempts+1>=max_attempts "
                "THEN 'failed' ELSE 'pending' END, attempts=attempts+1, "
                "worker_id=NULL,claim_token=NULL,lease_expires_at=NULL "
                "WHERE status='claimed' AND lease_expires_at<=?", (now,)
            )
            self.conn.commit()
            return cur.rowcount

    def claim(self, worker_id, event_types, lease_ttl=60, limit=1):
        with self.lock:
            now = time.time()
            self.conn.execute('BEGIN IMMEDIATE')
            marks = ','.join('?' for _ in event_types)
            rows = self.conn.execute(
                f"SELECT id FROM event_queue WHERE status='pending' AND "
                f"(next_retry_at IS NULL OR next_retry_at<=?) "
                f"AND event_type IN ({marks}) ORDER BY priority,id LIMIT ?",
                (now, *event_types, limit)
            ).fetchall()
            events = []
            for row in rows:
                token = uuid.uuid4().hex
                self.conn.execute(
                    "UPDATE event_queue SET status='claimed',worker_id=?,claim_token=?,"
                    "claimed_at=?,lease_expires_at=? WHERE id=?",
                    (worker_id, token, now, now+lease_ttl, row['id'])
                )
                events.append(dict(self.conn.execute(
                    'SELECT * FROM event_queue WHERE id=?', (row['id'],)
                ).fetchone()))
            self.conn.commit()
            return events

    def fail(self, event_id, worker_id, claim_token, error):
        with self.lock:
            row = self.conn.execute(
                "SELECT * FROM event_queue WHERE id=? AND status='claimed' "
                "AND worker_id=? AND claim_token=? AND lease_expires_at>?",
                (event_id, worker_id, claim_token, time.time())
            ).fetchone()
            if row is None:
                return False
            attempts = row['attempts'] + 1
            self.conn.execute(
                "UPDATE event_queue SET status=?,attempts=?,last_error=?,"
                "worker_id=NULL,claim_token=NULL,lease_expires_at=NULL WHERE id=?",
                ('failed' if attempts >= row['max_attempts'] else 'pending', attempts, error, event_id)
            )
            self.conn.commit()
            return True


class ControllerWorkerTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.db = FakeStateDB(str(Path(tmp.name)/'state.db'))
        self.addCleanup(self.db.conn.close)
        self.supervisor = WorkerSupervisor(self.db)
        self.supervisor.install_schema()
        self.worker = ControllerPhaseWorker(self.db, self.supervisor)
        self.worker.dispatcher.install_schema()
        self.bridge = ControllerPhaseBridge(self.db, lambda p, a: p == 'trusted-host')
        self.aid = next(iter(PHASE_BY_AUTOMATION))

    def add_phase(self, date='2026-10-19'):
        return self.bridge.enqueue(automation_id=self.aid, market_date=date, principal='trusted-host')

    def test_dispatch_and_replay_does_not_duplicate_instruction(self):
        event, created = self.add_phase()
        self.assertTrue(created)
        self.assertEqual(self.worker.run_once()['dispatched'], 1)
        self.assertEqual(self.worker.run_once()['dispatched'], 0)
        self.assertEqual(self.add_phase(), (event, False))
        self.assertEqual(self.db.conn.execute('SELECT COUNT(*) FROM controller_instruction').fetchone()[0], 1)
        self.assertEqual(self.db.conn.execute('SELECT status FROM event_queue WHERE id=?',(event,)).fetchone()[0], 'done')

    def test_competing_controller_worker_does_not_consume(self):
        other = self.supervisor.acquire('controller', ttl=60)
        self.add_phase()
        result = self.worker.run_once()
        self.assertEqual(result['blocked'], 'controller_role_occupied')
        self.assertEqual(self.db.conn.execute('SELECT COUNT(*) FROM controller_instruction').fetchone()[0], 0)
        self.assertTrue(self.supervisor.release(other))
        self.assertEqual(self.worker.run_once()['dispatched'], 1)

    def test_does_not_consume_execution_order(self):
        self.db.conn.execute("INSERT INTO event_queue(event_type,payload,created_at) VALUES('EXECUTE_ORDER','{}',?)", (int(time.time()),))
        self.db.conn.commit()
        self.assertEqual(self.worker.run_once()['claimed'], 0)
        self.assertEqual(self.db.conn.execute("SELECT status FROM event_queue WHERE event_type='EXECUTE_ORDER'").fetchone()[0], 'pending')

    def test_unauthorized_phase_cannot_enqueue(self):
        with self.assertRaises(PermissionError):
            self.bridge.enqueue(automation_id=self.aid, market_date='2026-10-19', principal='untrusted')
        self.assertEqual(self.worker.run_once()['dispatched'], 0)

    def test_restart_reclaims_expired_claim_once(self):
        event, _ = self.add_phase()
        self.db.conn.execute(
            "UPDATE event_queue SET status='claimed',worker_id='dead',claim_token='old',"
            "lease_expires_at=1 WHERE id=?", (event,)
        ); self.db.conn.commit()
        self.assertEqual(self.worker.run_once()['dispatched'], 1)
        self.assertEqual(self.db.conn.execute('SELECT attempts FROM event_queue WHERE id=?',(event,)).fetchone()[0], 1)
        self.assertEqual(self.worker.run_once()['dispatched'], 0)

    def test_uninstalled_dispatch_index_blocks_without_partial_instruction(self):
        self.add_phase()
        self.db.conn.execute('DROP INDEX idx_ctl_result_phase_event'); self.db.conn.commit()
        result = self.worker.run_once()
        self.assertEqual(result['failed'], 1)
        self.assertEqual(self.db.conn.execute('SELECT COUNT(*) FROM controller_instruction').fetchone()[0], 0)

    def test_occupied_role_released_after_failure(self):
        self.add_phase()
        self.db.conn.execute('DROP INDEX idx_ctl_result_phase_event'); self.db.conn.commit()
        self.worker.run_once()
        self.assertIsNotNone(self.supervisor.acquire('controller', ttl=60))

if __name__ == '__main__': unittest.main()

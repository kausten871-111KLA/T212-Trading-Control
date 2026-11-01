"""Regression: duplicate phase deliveries across independent SQLite connections.

No WebUI credentials, provider calls, schedules or broker activity. This uses
original PR17 schema and the staged bridge, but does not substitute for the
actual PR17 StateDB host-integration test.
"""
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from runtime.deepseek.controller_phase_bridge import ControllerPhaseBridge, PHASE_BY_AUTOMATION

SCHEMA = Path(__file__).resolve().parents[1] / 'runtime/deepseek/schema.sql'

class StateDBContract:
    def __init__(self, path, initialize=False):
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False, timeout=5)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('PRAGMA busy_timeout=5000')
        self.conn.execute('PRAGMA journal_mode=WAL')
        self.conn.execute('PRAGMA foreign_keys=ON')
        if initialize:
            self.conn.executescript(SCHEMA.read_text())
            self.conn.execute('ALTER TABLE event_queue ADD COLUMN claim_token TEXT')
            self.conn.commit()

class CrossConnectionPhaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / 'state.db')
        self.primary = StateDBContract(self.path, initialize=True)
        self.addCleanup(self.primary.conn.close)
        self.automation = next(iter(PHASE_BY_AUTOMATION))
        self.date = '2026-10-19'
        self.auth = lambda principal, automation: principal == 'authenticated-host' and automation == self.automation

    def test_sixteen_independent_connections_emit_exactly_once(self):
        def enqueue(_):
            db = StateDBContract(self.path)
            try:
                return ControllerPhaseBridge(db, self.auth).enqueue(
                    automation_id=self.automation, market_date=self.date, principal='authenticated-host')
            finally:
                db.conn.close()
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(enqueue, range(16)))
        ids = {event_id for event_id, _ in results}
        self.assertEqual(len(ids), 1)
        self.assertEqual(sum(created for _, created in results), 1)
        self.assertEqual(self.primary.conn.execute('SELECT COUNT(*) FROM event_queue').fetchone()[0], 1)

    def test_replay_preserves_terminal_status_across_connections(self):
        bridge = ControllerPhaseBridge(self.primary, self.auth)
        event_id, created = bridge.enqueue(automation_id=self.automation, market_date=self.date,
                                           principal='authenticated-host')
        self.assertTrue(created)
        self.primary.conn.execute("UPDATE event_queue SET status='done', attempts=2 WHERE id=?", (event_id,))
        self.primary.conn.commit()
        secondary = StateDBContract(self.path)
        try:
            self.assertEqual(ControllerPhaseBridge(secondary, self.auth).enqueue(
                automation_id=self.automation, market_date=self.date, principal='authenticated-host'),
                (event_id, False))
        finally:
            secondary.conn.close()
        status = self.primary.conn.execute('SELECT status, attempts FROM event_queue WHERE id=?', (event_id,)).fetchone()
        self.assertEqual(tuple(status), ('done', 2))

    def test_unauthorized_host_cannot_read_existing_phase_status(self):
        bridge = ControllerPhaseBridge(self.primary, self.auth)
        bridge.enqueue(automation_id=self.automation, market_date=self.date, principal='authenticated-host')
        with self.assertRaises(PermissionError):
            bridge.status(automation_id=self.automation, market_date=self.date, principal='unauthenticated')

if __name__ == '__main__':
    unittest.main()

"""Regression: controller phase worker must not requeue expired order events."""
import tempfile
import time
import unittest
from pathlib import Path
from tests.test_controller_worker import FakeStateDB
from runtime.deepseek.controller_phase_bridge import ControllerPhaseBridge, PHASE_BY_AUTOMATION
from runtime.deepseek.controller_worker import ControllerPhaseWorker
from runtime.deepseek.worker_supervisor import WorkerSupervisor


class ScopedRecoveryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = FakeStateDB(str(Path(tmp.name) / 'state.db'))
        self.addCleanup(self.db.conn.close)
        self.supervisor = WorkerSupervisor(self.db)
        self.supervisor.install_schema()
        self.worker = ControllerPhaseWorker(self.db, self.supervisor)
        self.worker.dispatcher.install_schema()
        self.bridge = ControllerPhaseBridge(self.db, lambda principal, aid: principal == 'trusted-host')
        self.aid = next(iter(PHASE_BY_AUTOMATION))

    def test_expired_order_claim_remains_untouched_by_phase_worker(self):
        self.db.conn.execute(
            "INSERT INTO event_queue(event_type,payload,created_at,status,worker_id,claim_token,"
            "lease_expires_at,attempts) VALUES('EXECUTE_ORDER','{}',?,'claimed','executor',"
            "'order-token',1,2)", (int(time.time()),)
        )
        self.db.conn.commit()
        self.assertEqual(self.worker.run_once()['dispatched'], 0)
        row = self.db.conn.execute(
            "SELECT status,worker_id,claim_token,attempts,lease_expires_at FROM event_queue "
            "WHERE event_type='EXECUTE_ORDER'"
        ).fetchone()
        self.assertEqual(tuple(row), ('claimed', 'executor', 'order-token', 2, 1))

    def test_expired_phase_claim_requeues_and_dispatches(self):
        event_id, _ = self.bridge.enqueue(
            automation_id=self.aid, market_date='2026-10-19', principal='trusted-host'
        )
        self.db.conn.execute(
            "UPDATE event_queue SET status='claimed',worker_id='dead',claim_token='old',"
            "lease_expires_at=1 WHERE id=?", (event_id,)
        )
        self.db.conn.commit()
        self.assertEqual(self.worker.run_once()['dispatched'], 1)
        row = self.db.conn.execute(
            'SELECT status,attempts FROM event_queue WHERE id=?', (event_id,)
        ).fetchone()
        self.assertEqual(tuple(row), ('done', 1))

    def test_exhausted_phase_claim_is_failed_without_dispatch(self):
        event_id, _ = self.bridge.enqueue(
            automation_id=self.aid, market_date='2026-10-20', principal='trusted-host'
        )
        self.db.conn.execute(
            "UPDATE event_queue SET status='claimed',worker_id='dead',claim_token='old',"
            "lease_expires_at=1,attempts=4,max_attempts=5 WHERE id=?", (event_id,)
        )
        self.db.conn.commit()
        self.assertEqual(self.worker.run_once()['dispatched'], 0)
        row = self.db.conn.execute(
            'SELECT status,attempts FROM event_queue WHERE id=?', (event_id,)
        ).fetchone()
        self.assertEqual(tuple(row), ('failed', 5))


if __name__ == '__main__':
    unittest.main()

"""Regression: leased recovery must not cross controller/executor event domains.

Use PR17's real StateDB and disposable SQLite files. No provider or broker calls.
"""
from pathlib import Path
from unittest.mock import Mock
import tempfile
import unittest

from runtime.deepseek.orchestrator import Orchestrator, StateDB


class ScopedExpiredClaimRecovery(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = StateDB(str(Path(self.temp.name) / "events.sqlite"))
        self.addCleanup(self.db.conn.close)
        self.db.init_schema()

    def claimed(self, event_type, owner):
        event_id = self.db.emit(event_type, {})
        claim = self.db.claim(owner, (event_type,))[0]
        self.assertEqual(claim["id"], event_id)
        self.db.conn.execute(
            "UPDATE event_queue SET lease_expires_at=0 WHERE id=?", (event_id,))
        self.db.conn.commit()
        return claim

    def row(self, event_id):
        return dict(self.db.conn.execute(
            "SELECT * FROM event_queue WHERE id=?", (event_id,)).fetchone())

    def test_controller_recovery_does_not_take_expired_order_claim(self):
        phase = self.claimed("MARKET_OPEN", "controller")
        order = self.claimed("EXECUTE_ORDER", "executor")
        self.assertEqual(self.db.requeue_dead(("MARKET_OPEN",)), 1)
        self.assertEqual(self.row(phase["id"])["status"], "pending")
        after = self.row(order["id"])
        self.assertEqual(after["status"], "claimed")
        self.assertEqual(after["worker_id"], "executor")
        self.assertEqual(after["claim_token"], order["claim_token"])
        self.assertEqual(after["attempts"], 0)

    def test_executor_recovery_is_separate_from_phase(self):
        phase = self.claimed("MARKET_CLOSE", "controller")
        order = self.claimed("EXECUTE_ORDER", "executor")
        self.assertEqual(self.db.requeue_dead(("EXECUTE_ORDER",)), 1)
        self.assertEqual(self.row(phase["id"])["status"], "claimed")
        self.assertEqual(self.row(order["id"])["status"], "pending")
        self.assertFalse(self.db.complete(order["id"], "executor", order["claim_token"]))

    def test_unspecified_scope_is_rejected_without_mutation(self):
        phase = self.claimed("MARKET_MIDDAY", "controller")
        for bad in (None, (), "MARKET_MIDDAY", [""], 123):
            with self.subTest(scope=bad), self.assertRaises(ValueError):
                self.db.requeue_dead(bad)
        self.assertEqual(self.row(phase["id"])["status"], "claimed")

    def test_exhausted_claim_is_failed_without_replay(self):
        phase = self.claimed("MARKET_CLOSE", "controller")
        self.db.conn.execute(
            "UPDATE event_queue SET max_attempts=1 WHERE id=?", (phase["id"],))
        self.db.conn.commit()
        self.assertEqual(self.db.requeue_dead(("MARKET_CLOSE",)), 1)
        self.assertEqual(self.row(phase["id"])["status"], "failed")
        self.assertEqual(self.row(phase["id"])["attempts"], 1)

    def test_live_claim_not_recovered(self):
        event_id = self.db.emit("EXECUTE_ORDER", {})
        self.db.claim("executor", ("EXECUTE_ORDER",), lease_ttl=60)
        self.assertEqual(self.db.requeue_dead(("EXECUTE_ORDER",)), 0)
        self.assertEqual(self.row(event_id)["status"], "claimed")

    def test_worker_loop_explicitly_passes_its_event_domain(self):
        db = Mock()
        db.claim.return_value = []
        runtime = Orchestrator(db, None, None)
        runtime.stop_event = Mock()
        runtime.stop_event.is_set.side_effect = [False, True]
        runtime.worker_loop("scout", lambda _: None, ("PREMARKET_INGEST",), poll=0)
        db.requeue_dead.assert_called_once_with(("PREMARKET_INGEST",))
        db.claim.assert_called_once_with("scout", ("PREMARKET_INGEST",), lease_ttl=60)


if __name__ == "__main__":
    unittest.main()

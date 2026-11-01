"""RT-14 model terminal -> controller ACK integration, offline SQLite only."""
import json
import tempfile
import unittest
import uuid
from pathlib import Path

from runtime.deepseek.service import migrate
from runtime.deepseek.orchestrator import StateDB
from runtime.deepseek.controller_phase_bridge import ControllerPhaseBridge, PHASE_BY_AUTOMATION
from runtime.deepseek.controller_dispatch import ControllerPhaseDispatcher
from runtime.deepseek.controller_ack import ControllerAcknowledgements
from runtime.deepseek.model_invocation_gate import ModelInvocationGate
from runtime.deepseek.model_terminal_ack import ModelTerminalAcknowledger


class ModelTerminalAckIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "runtime.db"
        migrate(self.path)
        self.db = StateDB(str(self.path))
        self.addCleanup(self.db.conn.close)
        self.aid = next(iter(PHASE_BY_AUTOMATION))
        self.auth = lambda principal, aid: principal == "host" and aid == self.aid
        event_id, created = ControllerPhaseBridge(self.db, self.auth).enqueue(
            automation_id=self.aid, market_date="2026-10-19", principal="host")
        self.assertTrue(created)
        self.db.conn.execute(
            "UPDATE event_queue SET status='claimed',worker_id='worker',"
            "claim_token='token',lease_expires_at=9999999999 WHERE id=?",
            (event_id,))
        self.db.conn.commit()
        self.instruction_id, created = ControllerPhaseDispatcher(self.db).dispatch_claim(
            {"id": event_id, "worker_id": "worker", "claim_token": "token"})
        self.assertTrue(created)
        self.verified = False
        self.verifier = lambda p, c, m, s: (
            self.verified and p == "host" and c == "chat" and m == "message"
            and s in ("completed", "failed"))
        self.gate = ModelInvocationGate(
            self.db, authorizer=self.auth, verify_terminal=self.verifier)
        self.acks = ControllerAcknowledgements(self.db, self.auth)
        self.bridge = ModelTerminalAcknowledger(self.gate, self.acks)
        self.invocation = str(uuid.uuid4())

    def claim(self):
        return self.gate.claim(
            instruction_id=self.instruction_id, principal="host",
            invocation_id=self.invocation, chat_id="chat")

    def complete(self, terminal="completed"):
        return self.gate.complete(
            instruction_id=self.instruction_id, principal="host",
            invocation_id=self.invocation, chat_id="chat",
            message_id="message", terminal=terminal)

    def ack(self, principal="host"):
        return self.bridge.acknowledge_verified(
            instruction_id=self.instruction_id, principal=principal)

    def outcome(self):
        return self.acks.status(
            instruction_id=self.instruction_id, principal="host")

    def test_unknown_claim_never_acknowledges_or_reinvokes(self):
        self.assertTrue(self.claim()[1])
        self.assertFalse(self.claim()[1])
        with self.assertRaisesRegex(RuntimeError, "No host-verified"):
            self.ack()
        self.assertEqual(self.outcome()["status"], "issued")
        self.assertEqual(self.gate.status(
            instruction_id=self.instruction_id, principal="host")["state"],
            "invocation_unknown")

    def test_verified_terminal_ack_is_idempotent_and_not_a_fill(self):
        self.claim()
        self.verified = True
        self.complete()
        first = self.ack()
        self.assertTrue(first[1])
        self.assertEqual(self.ack(), (first[0], False))
        status = self.outcome()
        self.assertEqual(status["status"], "acknowledged")
        self.assertEqual(status["outcome"]["model_terminal"], "completed")
        self.assertEqual(status["outcome"]["kind"], "verified_model_terminal")
        self.assertFalse(set(status["outcome"]) &
                         {"broker_fill", "order_id", "position", "pnl"})
        self.assertEqual(self.db.conn.execute(
            "SELECT COUNT(*) FROM controller_result WHERE kind='CONTROLLER_ACK'"
        ).fetchone()[0], 1)

    def test_failed_model_is_not_reported_as_success(self):
        self.claim()
        self.verified = True
        self.complete("failed")
        self.ack()
        self.assertEqual(self.outcome()["outcome"]["model_terminal"], "failed")

    def test_rejected_terminal_verifier_cannot_ack(self):
        self.claim()
        with self.assertRaises(PermissionError):
            self.complete()
        with self.assertRaises(RuntimeError):
            self.ack()
        self.assertEqual(self.outcome()["status"], "issued")

    def test_unauthorised_principal_cannot_ack(self):
        self.claim()
        self.verified = True
        self.complete()
        with self.assertRaises(PermissionError):
            self.ack("other")
        self.assertEqual(self.outcome()["status"], "issued")

    def test_wrong_invocation_identity_rejected(self):
        self.claim()
        self.verified = True
        with self.assertRaisesRegex(ValueError, "matching durable invocation"):
            self.gate.complete(
                instruction_id=self.instruction_id, principal="host",
                invocation_id=str(uuid.uuid4()), chat_id="chat",
                message_id="message", terminal="completed")
        with self.assertRaises(RuntimeError):
            self.ack()

    def test_restart_between_terminal_and_ack_does_not_reinvoke(self):
        self.claim()
        self.verified = True
        self.complete()
        second_db = StateDB(str(self.path))
        try:
            gate = ModelInvocationGate(
                second_db, authorizer=self.auth, verify_terminal=self.verifier)
            ack = ControllerAcknowledgements(second_db, self.auth)
            bridge = ModelTerminalAcknowledger(gate, ack)
            self.assertFalse(gate.claim(
                instruction_id=self.instruction_id, principal="host",
                invocation_id=self.invocation, chat_id="chat")[1])
            first = bridge.acknowledge_verified(
                instruction_id=self.instruction_id, principal="host")
            self.assertTrue(first[1])
            self.assertEqual(bridge.acknowledge_verified(
                instruction_id=self.instruction_id, principal="host"),
                (first[0], False))
        finally:
            second_db.conn.close()

    def test_migration_indexes_installed(self):
        indexes = {row[0] for row in self.db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'")}
        self.assertTrue({
            "idx_model_invocation_claim_once",
            "idx_model_invocation_result_once",
            "idx_controller_ack_once",
        } <= indexes)


if __name__ == "__main__":
    unittest.main()

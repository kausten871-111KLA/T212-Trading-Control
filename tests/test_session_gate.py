import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
GATE_PATH = ROOT / "worker" / "session_gate.py"
SPEC = importlib.util.spec_from_file_location("session_gate", GATE_PATH)
GATE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(GATE)


class SessionGateTests(unittest.TestCase):
    def test_summer_boundary_opens_at_1420_london(self):
        before = GATE.evaluate_session(datetime(2026, 10, 2, 13, 19, tzinfo=timezone.utc))
        start = GATE.evaluate_session(datetime(2026, 10, 2, 13, 20, tzinfo=timezone.utc))
        self.assertFalse(before.allowed)
        self.assertTrue(start.allowed)
        self.assertIn("14:20", start.observed_at_local)

    def test_winter_boundary_uses_gmt_without_code_change(self):
        decision = GATE.evaluate_session(datetime(2026, 12, 1, 14, 20, tzinfo=timezone.utc))
        self.assertTrue(decision.allowed)
        self.assertIn("+00:00", decision.observed_at_local)

    def test_weekend_is_rejected(self):
        decision = GATE.evaluate_session(datetime(2026, 10, 3, 13, 20, tzinfo=timezone.utc))
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "weekend")

    def test_last_slot_accepts_bounded_misfire_but_not_next_slot(self):
        london = ZoneInfo("Europe/London")
        last_slot = GATE.evaluate_session(datetime(2026, 10, 2, 21, 9, 59, tzinfo=london))
        too_late = GATE.evaluate_session(datetime(2026, 10, 2, 21, 10, 0, tzinfo=london))
        self.assertTrue(last_slot.allowed)
        self.assertFalse(too_late.allowed)

    def test_naive_datetime_fails_closed(self):
        with self.assertRaises(ValueError):
            GATE.evaluate_session(datetime(2026, 10, 2, 14, 20))

    def test_completed_slot_cannot_run_twice(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            slot = "2026-10-02T14:20:00+01:00"
            guard = GATE.RunSlotGuard(lock_path=base / "run.lock", state_path=base / "state.json")
            guard.acquire()
            self.assertEqual(guard.start(slot), 1)
            guard.complete()
            guard.release()

            duplicate = GATE.RunSlotGuard(lock_path=base / "run.lock", state_path=base / "state.json")
            duplicate.acquire()
            with self.assertRaises(GATE.DuplicateSlot):
                duplicate.start(slot)
            duplicate.release()

    def test_failed_slot_has_one_bounded_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            slot = "2026-10-02T14:25:00+01:00"
            first = GATE.RunSlotGuard(lock_path=base / "run.lock", state_path=base / "state.json")
            first.acquire()
            self.assertEqual(first.start(slot), 1)
            first.fail()
            first.release()

            second = GATE.RunSlotGuard(lock_path=base / "run.lock", state_path=base / "state.json")
            second.acquire()
            self.assertEqual(second.start(slot), 2)
            second.fail()
            second.release()

            exhausted = GATE.RunSlotGuard(lock_path=base / "run.lock", state_path=base / "state.json")
            exhausted.acquire()
            with self.assertRaises(GATE.SlotAttemptsExhausted):
                exhausted.start(slot)
            exhausted.release()

    def test_process_lock_rejects_overlap(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            first = GATE.RunSlotGuard(lock_path=base / "run.lock", state_path=base / "state.json")
            second = GATE.RunSlotGuard(lock_path=base / "run.lock", state_path=base / "state.json")
            first.acquire()
            with self.assertRaises(GATE.RunAlreadyActive):
                second.acquire()
            first.release()


class WorkerGateOrderingTests(unittest.TestCase):
    def test_outside_window_returns_before_discovery_inputs(self):
        import worker.run_discovery_cycle as worker

        denied = GATE.SessionDecision(
            allowed=False,
            reason="outside_approved_window",
            observed_at_utc="2026-10-02T00:00:00+00:00",
            observed_at_local="2026-10-02T01:00:00+01:00",
            timezone="Europe/London",
            window="weekdays 14:20-21:05 Europe/London",
            slot_key=None,
        )
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            with (
                patch.object(worker, "STATUS_PATH", base / "status.json"),
                patch.object(worker, "LOG_PATH", base / "worker.jsonl"),
                patch.object(worker, "evaluate_session", return_value=denied),
                patch.object(worker, "run_cycle", side_effect=AssertionError("discovery must not run")),
            ):
                self.assertEqual(worker.main(), 0)
                status = json.loads((base / "status.json").read_text(encoding="utf-8"))
                self.assertTrue(status["skipped"])
                self.assertEqual(status["orders_submitted"], 0)


if __name__ == "__main__":
    unittest.main()

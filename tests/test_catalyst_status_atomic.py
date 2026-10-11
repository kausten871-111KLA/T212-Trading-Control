"""Status-file durability regressions, isolated from providers and broker."""
import json
import multiprocessing
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from worker.run_catalyst_consumer import atomic_json


def concurrent_write(path, value):
    atomic_json(Path(path), {"worker": value, "ok": True})


class StatusAtomicTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "status.json"

    def test_replace_is_private_and_json_is_intact(self):
        atomic_json(self.path, {"step": 1})
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        atomic_json(self.path, {"step": 2})
        self.assertEqual(json.loads(self.path.read_text()), {"step": 2})
        self.assertFalse(list(self.path.parent.glob("*.tmp")))

    def test_symlink_destination_is_rejected_without_modifying_target(self):
        target = Path(self.temp.name) / "protected.txt"
        target.write_text("retain")
        self.path.symlink_to(target)
        with self.assertRaises(OSError):
            atomic_json(self.path, {"step": 1})
        self.assertEqual(target.read_text(), "retain")
        self.assertTrue(self.path.is_symlink())

    def test_replace_failure_preserves_previous_status_and_cleans_temp(self):
        atomic_json(self.path, {"stable": True})
        existing = self.path.read_bytes()
        with patch.object(Path, "replace", side_effect=OSError("synthetic replace failure")):
            with self.assertRaises(OSError):
                atomic_json(self.path, {"stable": False})
        self.assertEqual(self.path.read_bytes(), existing)
        self.assertFalse(list(self.path.parent.glob("*.tmp")))

    def test_invalid_payload_fails_without_corrupting_status(self):
        atomic_json(self.path, {"stable": True})
        old = self.path.read_bytes()
        with self.assertRaises(ValueError):
            atomic_json(self.path, {"invalid": float("nan")})
        self.assertEqual(self.path.read_bytes(), old)

    def test_four_concurrent_writers_leave_one_complete_record(self):
        children = [multiprocessing.Process(target=concurrent_write, args=(str(self.path), i)) for i in range(4)]
        for child in children:
            child.start()
        for child in children:
            child.join(10)
            self.assertFalse(child.is_alive())
            self.assertEqual(child.exitcode, 0)
        content = json.loads(self.path.read_text())
        self.assertTrue(content["ok"])
        self.assertIn(content["worker"], range(4))
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()

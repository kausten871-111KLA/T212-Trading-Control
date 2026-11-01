"""Offline tests for exact operator-only v0.12.4 staging synchronizer.

No SSH, Docker, production files, GitHub API or broker calls.
"""
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

SCRIPT = (Path(__file__).resolve().parents[1] /
          "deploy/deepseek/webui_tool_binding/v0124/sync_stage_operator.py")


def load_script():
    spec = importlib.util.spec_from_file_location("v0124_stage_sync_fixture", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OperatorStageSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.stage = Path(self.tmp.name) / "stage"
        self.stage.mkdir()
        self.module = load_script()
        self.module.STAGE = self.stage
        self.original = {
            "upgrade_supervised.sh": b"#!/bin/bash\necho old-upgrade\n",
            "v0124_acceptance.py": b"print('old-acceptance')\n",
            "v0124_restore_db.py": b"print('same-restore')\n",
        }
        self.target = {
            "upgrade_supervised.sh": b"#!/bin/bash\necho new-upgrade\n",
            "v0124_acceptance.py": b"print('new-acceptance')\n",
            "v0124_restore_db.py": self.original["v0124_restore_db.py"],
        }
        self.module.BEFORE = {k: self.module.blob_sha(v) for k, v in self.original.items()}
        self.module.TARGET = {k: self.module.blob_sha(v) for k, v in self.target.items()}
        self.module.OLD_STAGE_SHA256 = hashlib.sha256(self.original["upgrade_supervised.sh"]).hexdigest()
        for name, data in self.original.items():
            (self.stage / name).write_bytes(data)

    def test_exact_two_script_update_and_preflight(self):
        calls = []
        result = self.module.synchronize(self.target, check=lambda: calls.append("preflight"))
        self.assertEqual(result, "updated")
        self.assertEqual(calls, ["preflight"])
        for name, data in self.target.items():
            self.assertEqual((self.stage / name).read_bytes(), data)
        saved = list(self.stage.glob("v0124-stage-before-sync-*"))
        self.assertEqual(len(saved), 1)
        for name, data in self.original.items():
            self.assertEqual((saved[0] / name).read_bytes(), data)

    def test_refuse_unknown_stage_drift_without_changes(self):
        (self.stage / "v0124_acceptance.py").write_bytes(b"unexpected content")
        with self.assertRaisesRegex(RuntimeError, "Unexpected stage drift"):
            self.module.synchronize(self.target, check=lambda: self.fail("preflight must not run"))
        self.assertEqual((self.stage / "upgrade_supervised.sh").read_bytes(),
                         self.original["upgrade_supervised.sh"])
        self.assertEqual(list(self.stage.glob("v0124-stage-before-sync-*")), [])

    def test_preflight_failure_restores_all_staged_scripts(self):
        def reject():
            raise RuntimeError("preflight intentionally failed")
        with self.assertRaisesRegex(RuntimeError, "preflight intentionally failed"):
            self.module.synchronize(self.target, check=reject)
        for name, data in self.original.items():
            self.assertEqual((self.stage / name).read_bytes(), data)

    def test_idempotent_if_already_current(self):
        for name, data in self.target.items():
            (self.stage / name).write_bytes(data)
        calls = []
        result = self.module.synchronize(self.target, check=lambda: calls.append("preflight"))
        self.assertEqual(result, "already-current")
        self.assertEqual(calls, ["preflight"])
        self.assertEqual(list(self.stage.glob("v0124-stage-before-sync-*")), [])

    def test_reject_source_blob_mismatch_before_copy(self):
        wrong = dict(self.target)
        wrong["upgrade_supervised.sh"] = b"tampered source"
        with self.assertRaisesRegex(RuntimeError, "Source verification failed"):
            self.module.synchronize(wrong, check=lambda: self.fail("no preflight"))
        for name, data in self.original.items():
            self.assertEqual((self.stage / name).read_bytes(), data)


if __name__ == "__main__":
    unittest.main()

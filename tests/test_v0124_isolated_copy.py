"""Offline regressions for a preserved, already-backed-up v0.12.4 stage source.

Tests exercise the static immutable SQLite snapshot copier, without Docker,
WebUI, network, production volumes, cloud providers or broker orders.
"""
import hashlib
import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "deploy/deepseek/webui_tool_binding/v0124/run_isolated_db_acceptance.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location("v0124_isolated_copy_test_module", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ArchivedSqliteCopyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.backup = self.root / "backup"
        self.backup_data = self.backup / "data"
        self.backup_data.mkdir(parents=True)
        self.db = self.backup_data / "webui.db"
        with sqlite3.connect(str(self.db)) as db:
            for i in range(48):
                db.execute(f"CREATE TABLE fixture_{i:02d} (id INTEGER PRIMARY KEY)")
            db.commit()
        (self.backup_data / "blobs").mkdir()
        (self.backup_data / "blobs" / "file.bin").write_bytes(b"cache blob")
        (self.backup_data / "cache").mkdir()
        self.link = self.backup_data / "cache" / "link.bin"
        self.link.symlink_to("../blobs/file.bin")
        self.stage = self.root / "data-test-retry-1"
        self.module = load_module()
        self.module.BACKUP = self.backup
        self.module.DATA = self.stage

    def test_immutable_archive_can_be_verified_and_copied(self):
        before = digest(self.db)
        self.assertEqual(self.module.verify_snapshot(self.db), 48)
        self.module.copy_verified_snapshot()
        self.assertEqual(digest(self.db), before)
        self.assertEqual(digest(self.stage / "webui.db"), before)
        self.assertEqual(self.module.verify_snapshot(self.stage / "webui.db"), 48)
        self.assertTrue((self.stage / "cache" / "link.bin").is_symlink())
        self.assertEqual((self.stage / "cache" / "link.bin").read_bytes(), b"cache blob")

    def test_second_run_cannot_overwrite_existing_stage(self):
        self.module.copy_verified_snapshot()
        first = digest(self.stage / "webui.db")
        with self.assertRaisesRegex(AssertionError, "Retry stage already exists"):
            self.module.copy_verified_snapshot()
        self.assertEqual(digest(self.stage / "webui.db"), first)

    def test_rejects_symlink_outside_archive(self):
        self.link.unlink()
        outside = self.root / "outside.bin"
        outside.write_bytes(b"must not copy")
        self.link.symlink_to("../../../outside.bin")
        with self.assertRaisesRegex(AssertionError, "Archive link escape"):
            self.module.copy_verified_snapshot()
        self.assertFalse(self.stage.exists())

    def test_rejects_archive_with_bad_database_integrity(self):
        self.db.write_bytes(b"not-a-valid-sqlite-backup")
        with self.assertRaises(sqlite3.DatabaseError):
            self.module.copy_verified_snapshot()
        self.assertFalse(self.stage.exists())


if __name__ == "__main__":
    unittest.main()

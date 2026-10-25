"""Offline regressions for the EXACT in-container v0.12.4 archive copier.

The production runner pipes COPY_SNAPSHOT to a network-disabled Docker
helper; these tests execute that same Python source against disposable
temporary fixtures, without Docker, WebUI, network, broker or secrets.
"""
import contextlib
import hashlib
import importlib.util
import io
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
        self.backup_data = self.root / "backup" / "data"
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
        self.stage = self.root / "new-stage"
        self.module = load_module()

    def run_actual_helper_source(self):
        self.stage.mkdir()
        code = self.module.COPY_SNAPSHOT
        self.assertEqual(code.count('src=Path("/source")'),1)
        self.assertEqual(code.count('dst=Path("/dest")'),1)
        code = code.replace('src=Path("/source")',f"src=Path({str(self.backup_data)!r})")
        code = code.replace('dst=Path("/dest")',f"dst=Path({str(self.stage)!r})")
        with contextlib.redirect_stdout(io.StringIO()) as captured:
            exec(compile(code, str(SCRIPT), "exec"), {})
        return captured.getvalue()

    def test_immutable_archive_copied_with_hash_and_symlinks(self):
        before=digest(self.db)
        output=self.run_actual_helper_source()
        self.assertIn("V0124_BACKUP_COPY_PASS",output)
        self.assertEqual(digest(self.db),before)
        self.assertEqual(digest(self.stage/"webui.db"),before)
        self.assertTrue((self.stage/"cache"/"link.bin").is_symlink())
        self.assertEqual((self.stage/"cache"/"link.bin").read_bytes(),b"cache blob")

    def test_refuses_to_overwrite_nonempty_stage(self):
        self.stage.mkdir()
        marker=self.stage/"do-not-overwrite"
        marker.write_text("original")
        code=self.module.COPY_SNAPSHOT
        code=code.replace('src=Path("/source")',f"src=Path({str(self.backup_data)!r})")
        code=code.replace('dst=Path("/dest")',f"dst=Path({str(self.stage)!r})")
        with self.assertRaisesRegex(AssertionError,"Refusing to overwrite"):
            exec(compile(code,str(SCRIPT),"exec"),{})
        self.assertEqual(marker.read_text(),"original")

    def test_rejects_symlink_outside_archive(self):
        self.link.unlink()
        outside=self.root/"outside.bin"
        outside.write_bytes(b"must not copy")
        self.link.symlink_to("../../../outside.bin")
        with self.assertRaisesRegex(AssertionError,"Archive symlink escape"):
            self.run_actual_helper_source()
        self.assertFalse((self.stage/"webui.db").exists())

    def test_rejects_corrupt_archive_without_copy(self):
        self.db.write_bytes(b"not-a-valid-sqlite-backup")
        with self.assertRaises(sqlite3.DatabaseError):
            self.run_actual_helper_source()
        self.assertFalse((self.stage/"webui.db").exists())

    def test_rejects_absolute_archive_symlink(self):
        self.link.unlink()
        self.link.symlink_to(self.backup_data/"blobs"/"file.bin")
        with self.assertRaisesRegex(AssertionError,"Absolute archive symlink"):
            self.run_actual_helper_source()
        self.assertFalse((self.stage/"webui.db").exists())

if __name__=="__main__":
    unittest.main()

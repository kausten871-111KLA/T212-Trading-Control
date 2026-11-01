"""Run the EXACT embedded pre-stop rollback SQLite probe on isolated fixtures.

No Docker, production database, network, model or broker access.
"""
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

SCRIPT = (Path(__file__).resolve().parents[1] /
          "deploy/deepseek/webui_tool_binding/v0124/upgrade_supervised.sh")


class RollbackSnapshotSqliteIntegrity(unittest.TestCase):
    def actual_python_probe(self):
        shell = SCRIPT.read_text()
        anchor = '--entrypoint python "$OLD" -c ' + chr(39) + '\n'
        end = '\n' + chr(39) + '; then'
        self.assertEqual(shell.count(anchor), 1)
        embedded = shell.split(anchor, 1)[1].split(end, 1)[0]
        compile(embedded, "<actual-rollback-sqlite-probe>", "exec")
        self.assertIn("mode=ro&immutable=1", embedded)
        self.assertIn("PRAGMA integrity_check", embedded)
        self.assertIn("len(names)>=48", embedded)
        for name in ("automation", "model", "tool", "user"):
            self.assertIn(name, embedded)
        return embedded

    def run_probe(self, embedded, db_path):
        uri = db_path.as_uri() + "?mode=ro&immutable=1"
        exact = "file:/source/webui.db?mode=ro&immutable=1"
        self.assertEqual(embedded.count(exact), 1)
        probe = embedded.replace(exact, uri)
        return subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True, text=True, timeout=10,
        )

    def test_48_table_integrity_passes_47_and_corrupt_fail(self):
        probe = self.actual_python_probe()
        with tempfile.TemporaryDirectory() as temp:
            db_file = Path(temp) / "snapshot.db"
            with sqlite3.connect(db_file) as db:
                for index in range(48):
                    db.execute(f"create table stage_{index} (id integer primary key)")
                db.commit()
            foreign_schema = self.run_probe(probe, db_file)
            self.assertEqual(foreign_schema.returncode, 1, foreign_schema.stderr)
            with sqlite3.connect(db_file) as db:
                for index in range(4):
                    db.execute(f"drop table stage_{index}")
                for name in ("automation", "model", "tool"):
                    db.execute(f"create table {name} (id integer primary key)")
                db.commit()
            bad_count = self.run_probe(probe, db_file)
            self.assertEqual(bad_count.returncode, 1, bad_count.stderr)
            with sqlite3.connect(db_file) as db:
                db.execute("create table user (id integer primary key)")
                db.commit()
            good = self.run_probe(probe, db_file)
            self.assertEqual(good.returncode, 0, good.stderr)
            db_file.write_bytes(b"corrupt not a SQLite database")
            corrupt = self.run_probe(probe, db_file)
            self.assertEqual(corrupt.returncode, 1, corrupt.stderr)


if __name__ == "__main__":
    unittest.main()

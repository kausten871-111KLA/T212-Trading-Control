import importlib.util
import time
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "server_deployment_preflight.py"
SPEC = importlib.util.spec_from_file_location("server_deployment_preflight", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class ServerDeploymentPreflightTests(unittest.TestCase):
    def setUp(self):
        self.now = time.time()
        self.commit = "a" * 40
        self.snapshot = {
            "git_branch": MODULE.DEFAULT_BRANCH,
            "git_commit": self.commit,
            "git_clean": True,
            "container_running": True,
            "database": {"path": "/app/backend/data/webui.db", "size": 4096, "mtime": self.now},
            "database_backups": [
                {"path": "/app/backend/data/webui_backup_20261001.db", "size": 4096, "mtime": self.now - 3600}
            ],
            "tool_backups": [
                {"path": "/app/backend/data/tool_table_backup_20261001.json", "size": 512, "mtime": self.now - 1800}
            ],
            "disk_free_bytes": 5 * 1024**3,
            "repository_preflight": True,
            "safety": {
                "environment": "DEMO",
                "live_trading_enabled": False,
                "order_mutation_enabled": False,
            },
        }

    def assess(self, expected_commit=None):
        return MODULE.assess(
            self.snapshot,
            now_epoch=self.now,
            max_backup_age_hours=24,
            min_disk_bytes=1024**3,
            expected_branch=MODULE.DEFAULT_BRANCH,
            expected_commit=expected_commit,
        )

    def test_ready_with_exact_commit(self):
        report = self.assess(self.commit)
        self.assertEqual(report["status"], "READY")
        self.assertEqual(report["failed_checks"], [])
        self.assertEqual(report["side_effects"], "none")

    def test_ready_for_commit_approval_without_pin(self):
        report = self.assess()
        self.assertEqual(report["status"], "READY_FOR_COMMIT_APPROVAL")
        self.assertNotIn("expected_commit", [item["name"] for item in report["checks"]])

    def test_stale_backup_fails_closed(self):
        self.snapshot["database_backups"][0]["mtime"] = self.now - 25 * 3600
        report = self.assess(self.commit)
        self.assertEqual(report["status"], "NOT_READY")
        self.assertIn("database_backup", report["failed_checks"])

    def test_dirty_worktree_fails_closed(self):
        self.snapshot["git_clean"] = False
        report = self.assess(self.commit)
        self.assertIn("clean_worktree", report["failed_checks"])

    def test_live_or_mutating_safety_fails_closed(self):
        self.snapshot["safety"]["live_trading_enabled"] = True
        report = self.assess(self.commit)
        self.assertIn("demo_safety", report["failed_checks"])

    def test_commit_mismatch_fails_closed(self):
        report = self.assess("b" * 40)
        self.assertIn("expected_commit", report["failed_checks"])

    def test_file_stats_are_parsed_and_sorted(self):
        stats = MODULE.parse_file_stats(
            "/data/older.db|10|100.5\n/data/newer.db|20|200.25\ninvalid\n"
        )
        self.assertEqual(stats[0]["path"], "/data/newer.db")
        self.assertEqual(stats[0]["size"], 20)

    def test_empty_and_zero_size_backup_fail(self):
        self.snapshot["tool_backups"] = []
        report = self.assess(self.commit)
        self.assertIn("tool_table_backup", report["failed_checks"])


if __name__ == "__main__":
    unittest.main()

"""Regression: a failed Docker stop MUST NOT restore SQLite while WebUI runs.

Exercises the exact rollback() shell body from the supervised v0.12.4
upgrade script. All paths, Docker calls, systemctl, and readiness are
isolated/mocked; no production server or broker is accessed.
"""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

SCRIPT = (Path(__file__).resolve().parents[1] /
          "deploy/deepseek/webui_tool_binding/v0124/upgrade_supervised.sh")
OLD_ID = "sha256:7d8d04ead2b7c38d99b12b80a777b6030f3c694c491ca93e6bb010b5c3e82483"
OLD = "local/open-webui-toolbinding-v0123-stage:20261020"


class RollbackStoppedWriterGate(unittest.TestCase):
    def exact_function(self):
        text = SCRIPT.read_text()
        self.assertEqual(text.count("\nrollback() {\n"), 1)
        self.assertEqual(text.count("\non_error() {\n"), 1)
        function = "rollback() {\n" + text.split("\nrollback() {\n", 1)[1].split("\non_error() {\n", 1)[0]
        self.assertIn('if ! docker compose -f "$COMPOSE" stop open-webui; then', function)
        self.assertIn('docker inspect -f', function)
        self.assertIn('webui_still_running', function)
        self.assertIn('V0124_ROLLBACK_BLOCKED invalid_snapshot_sqlite', function)
        self.assertIn('mode=ro&immutable=1', function)
        return function

    def simulate(self, *, stop_fails=False, still_running=False, missing_snapshot=False, unexpected_image=False, invalid_snapshot=False):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backup = root / "webui-v0124-cutover-fixture"
            (backup / "data").mkdir(parents=True)
            if not missing_snapshot:
                (backup / "data" / "webui.db").write_bytes(b"test-DB-no-real-sqlite")
            (backup / "docker-compose.yml").write_text(
                "services:\n  open-webui:\n    image: " + OLD + "\n"
            )
            compose = root / "current-compose.yml"
            compose.write_text("PRE-ROLLBACK-COMPOSE-MARKER\n")
            restore = root / "v0124_restore_db.py"
            restore.write_text("NOT EXECUTED\n")
            before = compose.read_bytes()
            function = self.exact_function().replace(
                "/home/katie/backups/webui-v0124-cutover-", str(root) + "/webui-v0124-cutover-"
            )
            harness = (
                "set -Eeuo pipefail\n"
                f"COMPOSE={str(compose)!r}\n"
                f"OLD={OLD!r}\n"
                f"OLD_ID={OLD_ID!r}\n"
                f"RESTORE={str(restore)!r}\n"
                "NEW=mock-new-image\nDATA_VOL=mock-volume\n"
                "docker() {\n"
                "  if [[ \"$1\" == image && \"$2\" == inspect ]]; then printf '%s\\n' \"$MOCK_IMAGE_ID\"; return 0; fi\n"
                "  if [[ \"$1\" == compose && \"$4\" == stop ]]; then\n"
                "    echo MOCK_STOP_ATTEMPT; [[ \"$MOCK_STOP_FAIL\" == 0 ]]; return $?; fi\n"
                "  if [[ \"$1\" == inspect && \"$3\" == '{{.State.Running}}' ]]; then\n"
                "    printf '%s\\n' \"$MOCK_RUNNING\"; return 0; fi\n"
                "  if [[ \"$1\" == inspect && \"$3\" == '{{.Image}}' ]]; then\n"
                "    printf '%s\\n' \"$OLD_ID\"; return 0; fi\n"
                "  if [[ \"$1\" == run ]]; then\n"
                "    if [[ \" $* \" == *\" -c \"* ]]; then\n"
                "      echo MOCK_VERIFY_SNAPSHOT; [[ \"$MOCK_DB_INVALID\" == 0 ]]; return $?; fi\n"
                "    echo MOCK_RESTORE_SQLITE; return 0; fi\n"
                "  if [[ \"$1\" == compose && \"$4\" == up ]]; then echo MOCK_RESTART; return 0; fi\n"
                "  echo UNEXPECTED_DOCKER_ARGS \"$@\"; return 90\n"
                "}\n"
                "ready() { return 0; }\n"
                "systemctl() { return 0; }\n"
                + function + "\n"
                f"if rollback {str(backup)!r}; then echo MOCK_ROLLBACK_PASS; "
                "else echo MOCK_ROLLBACK_FAILED; fi\n"
            )
            result = subprocess.run(
                ["bash", "-c", harness], capture_output=True, text=True,
                env={"PATH": "/usr/bin:/bin",
                     "MOCK_STOP_FAIL": "1" if stop_fails else "0",
                     "MOCK_RUNNING": "true" if still_running else "false",
                     "MOCK_IMAGE_ID": "sha256:wrong" if unexpected_image else OLD_ID,
                     "MOCK_DB_INVALID": "1" if invalid_snapshot else "0"},
                timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout, compose.read_bytes() == before

    def test_stop_command_failure_preserves_compose_and_does_not_restore(self):
        output, unchanged = self.simulate(stop_fails=True, still_running=True)
        self.assertTrue(unchanged)
        self.assertIn("V0124_ROLLBACK_BLOCKED could_not_stop_webui", output)
        self.assertIn("MOCK_ROLLBACK_FAILED", output)
        self.assertNotIn("MOCK_RESTORE_SQLITE", output)
        self.assertNotIn("MOCK_RESTART", output)

    def test_stop_reports_success_but_writer_remains_running(self):
        output, unchanged = self.simulate(stop_fails=False, still_running=True)
        self.assertTrue(unchanged)
        self.assertIn("V0124_ROLLBACK_BLOCKED webui_still_running", output)
        self.assertIn("MOCK_ROLLBACK_FAILED", output)
        self.assertNotIn("MOCK_RESTORE_SQLITE", output)

    def test_missing_backup_db_blocks_before_stop(self):
        output, unchanged = self.simulate(missing_snapshot=True)
        self.assertTrue(unchanged)
        self.assertIn("V0124_ROLLBACK_BLOCKED invalid_backup_or_image", output)
        self.assertIn("MOCK_ROLLBACK_FAILED", output)
        self.assertNotIn("MOCK_STOP_ATTEMPT", output)
        self.assertNotIn("MOCK_RESTORE_SQLITE", output)

    def test_wrong_pinned_old_image_blocks_before_stop(self):
        output, unchanged = self.simulate(unexpected_image=True)
        self.assertTrue(unchanged)
        self.assertIn("V0124_ROLLBACK_BLOCKED invalid_backup_or_image", output)
        self.assertNotIn("MOCK_STOP_ATTEMPT", output)
        self.assertNotIn("MOCK_RESTORE_SQLITE", output)

    def test_corrupt_sqlite_blocks_before_stop_and_restore(self):
        output, unchanged = self.simulate(invalid_snapshot=True)
        self.assertTrue(unchanged)
        self.assertIn("MOCK_VERIFY_SNAPSHOT", output)
        self.assertIn("V0124_ROLLBACK_BLOCKED invalid_snapshot_sqlite", output)
        self.assertNotIn("MOCK_STOP_ATTEMPT", output)
        self.assertNotIn("MOCK_RESTORE_SQLITE", output)

    def test_confirmed_stopped_writer_allows_restore_and_restart(self):
        output, _ = self.simulate(stop_fails=False, still_running=False)
        self.assertLess(output.index("MOCK_VERIFY_SNAPSHOT"), output.index("MOCK_STOP_ATTEMPT"))
        self.assertIn("MOCK_RESTORE_SQLITE", output)
        self.assertIn("MOCK_RESTART", output)
        self.assertIn("V0124_ROLLBACK_PASS", output)
        self.assertIn("MOCK_ROLLBACK_PASS", output)


if __name__ == "__main__":
    unittest.main()

"""Offline regression for the exact v0.12.4 manual rollback branch.

Uses a mock docker-inspect command and rollback function; no live Docker,
SSH, credentials, network, SQLite or production changes.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest

SOURCE = (Path(__file__).resolve().parents[1]
          / "deploy/deepseek/webui_tool_binding/v0124/upgrade_supervised.sh")
START = 'if [[ "$OP" == "--rollback" ]]; then'
END = '\n[[ "$OP" == "--check" || "$OP" == "--deploy" ]]'
OLD = "local/open-webui-toolbinding-v0123-stage:20261020"
NEW = "local/open-webui-toolbinding-v0124-stage:20261025"
OLD_ID = "sha256:7d8d04ead2b7c38d99b12b80a777b6030f3c694c491ca93e6bb010b5c3e82483"
NEW_ID = "sha256:9642e4c6bd781369b1647664cb8d85f254c5e22b5e2bf5538b9d0cb9ea487cf9"

class ManualRollbackIdempotence(unittest.TestCase):
    def branch(self):
        content = SOURCE.read_text()
        self.assertEqual(content.count(START), 1)
        self.assertEqual(content.count(END), 1)
        return START + content.split(START,1)[1].split(END,1)[0]

    def simulate(self, image_id, compose_image, *, expected_exit=0):
        with tempfile.TemporaryDirectory() as temp:
            compose = Path(temp) / "docker-compose.yml"
            compose.write_text("services:\n  open-webui:\n    image: "+compose_image+"\n")
            initial = compose.read_bytes()
            harness = (
                'set -Eeuo pipefail\n'
                'OP=--rollback\n'
                'set -- --rollback /nonexistent/mock-backup\n'
                'OLD='+OLD+'\n'
                'OLD_ID='+OLD_ID+'\n'
                'NEW='+NEW+'\n'
                'NEW_ID='+NEW_ID+'\n'
                'COMPOSE='+str(compose)+'\n'
                'docker() { printf "%s\\n" "$MOCK_IMAGE_ID"; }\n'
                'rollback() { echo "MOCK_ROLLBACK_INVOKED"; }\n'
                + self.branch() + '\n'
            )
            completed = subprocess.run(
                ["bash","-c",harness],capture_output=True,text=True,
                env={"PATH":"/usr/bin:/bin","MOCK_IMAGE_ID":image_id},
                timeout=10)
            self.assertEqual(completed.returncode,expected_exit,completed.stderr)
            self.assertEqual(compose.read_bytes(),initial)
            return completed.stdout

    def test_already_original_skips_restore(self):
        output=self.simulate(OLD_ID,OLD)
        self.assertIn("V0124_ALREADY_ORIGINAL no_restore_performed",output)
        self.assertNotIn("MOCK_ROLLBACK_INVOKED",output)

    def test_new_image_calls_restore(self):
        self.assertIn("MOCK_ROLLBACK_INVOKED",self.simulate(NEW_ID,NEW))

    def test_partial_compose_switch_calls_restore(self):
        self.assertIn("MOCK_ROLLBACK_INVOKED",self.simulate(OLD_ID,NEW))

    def test_partial_image_switch_calls_restore(self):
        self.assertIn("MOCK_ROLLBACK_INVOKED",self.simulate(NEW_ID,OLD))

    def test_unrelated_future_image_blocks_restore(self):
        output=self.simulate("sha256:unrelated-upgrade",NEW,expected_exit=2)
        self.assertIn("V0124_MANUAL_ROLLBACK_BLOCKED",output)
        self.assertNotIn("MOCK_ROLLBACK_INVOKED",output)

    def test_unrelated_future_compose_blocks_restore(self):
        output=self.simulate(NEW_ID,"local/other-webui:v0.12.5",expected_exit=2)
        self.assertIn("V0124_MANUAL_ROLLBACK_BLOCKED",output)
        self.assertNotIn("MOCK_ROLLBACK_INVOKED",output)

if __name__ == "__main__":
    unittest.main()

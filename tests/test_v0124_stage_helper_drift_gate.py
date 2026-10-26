"""Execute the actual v0.12.4 staged-helper hash gate against isolated fixtures.

No SSH, Docker, WebUI, network, secrets, paid providers or broker calls.
"""
from pathlib import Path
import importlib.util
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
STAGE = ROOT / "deploy/deepseek/webui_tool_binding/v0124"
UPGRADE = STAGE / "upgrade_supervised.sh"
SYNC = STAGE / "sync_stage_operator.py"


class StageHelperDriftGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name in ("v0124_acceptance.py", "v0124_restore_db.py"):
            shutil.copyfile(STAGE / name, self.root / name)

    def exact_gate(self):
        text = UPGRADE.read_text()
        start = "# Verify audited helper scripts before any production change."
        end = 'test "$(docker inspect -f'
        self.assertEqual(text.count(start), 1)
        self.assertIn(end, text.split(start, 1)[1])
        self.assertGreater(text.index(start), text.index('if [[ "$OP" == "--rollback" ]]'))
        self.assertLess(text.index(start), text.index('if [[ "$OP" == "--check" ]]'))
        self.assertLess(text.index(start), text.index("V0124_FRESH_BACKUP_PASS"))
        return text.split(start, 1)[1].split(end, 1)[0]

    def execute(self):
        gate = self.exact_gate()
        env = dict(os.environ)
        env["ACCEPT"] = str(self.root / "v0124_acceptance.py")
        env["RESTORE"] = str(self.root / "v0124_restore_db.py")
        return subprocess.run(
            ["bash", "-c", "set -euo pipefail\n" + gate + "\necho GATE_OK"],
            env=env, capture_output=True, text=True, timeout=10,
        )

    def test_pinned_unmodified_helpers_pass(self):
        result = self.execute()
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("GATE_OK", result.stdout)

    def test_stale_acceptance_blocks_before_cutover(self):
        (self.root / "v0124_acceptance.py").write_text("print('stale')\n")
        result = self.execute()
        self.assertEqual(result.returncode, 2)
        self.assertIn("V0124_STAGE_HELPER_DRIFT_BLOCKED", result.stdout)
        self.assertNotIn("GATE_OK", result.stdout)

    def test_modified_restore_blocks_before_cutover(self):
        with (self.root / "v0124_restore_db.py").open("a") as file:
            file.write("\n# unexpected modification\n")
        result = self.execute()
        self.assertEqual(result.returncode, 2)
        self.assertIn("V0124_STAGE_HELPER_DRIFT_BLOCKED", result.stdout)

    def test_operator_sync_pins_current_reviewed_sources(self):
        spec = importlib.util.spec_from_file_location("v0124_sync_integrity", SYNC)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(
            module.COMMIT, "1cdebe5afe0089cebff83c91bd0867618c541a2c"
        )
        for name, expected in module.TARGET.items():
            self.assertEqual(module.blob_sha((STAGE / name).read_bytes()), expected,
                             f"Operator sync target drifted: {name}")


if __name__ == "__main__":
    unittest.main()

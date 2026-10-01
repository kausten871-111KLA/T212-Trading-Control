import importlib.util
import json
import unittest
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "build_morning_handoff.py"
SPEC = importlib.util.spec_from_file_location("build_morning_handoff", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class MorningHandoffTests(unittest.TestCase):
    def setUp(self):
        self.config = MODULE.load_json(ROOT / "webui-control" / "morning-human-actions.json")
        self.manifest = MODULE.load_json(ROOT / "webui-control" / "release-manifest.json")
        self.commit = "a" * 40
        self.preflight = {
            "status": "PASS",
            "tests_run": 82,
            "configs_checked": ["a", "b"],
            "components_checked": ["a"],
            "failures": [],
        }

    def render(self, server_report=None):
        return MODULE.render_pack(
            self.config,
            self.manifest,
            self.preflight,
            commit=self.commit,
            branch="feature/t212-instrument-cache-v03",
            server_report=server_report,
        )

    def test_pack_pins_every_required_command_to_full_commit(self):
        rendered = self.render()
        self.assertGreaterEqual(rendered.count(self.commit), 3)
        self.assertIn("git merge --ff-only", rendered)
        self.assertIn("--expected-commit", rendered)

    def test_pack_contains_required_human_context(self):
        rendered = self.render()
        for label in ("Where:", "Success:", "If it fails:", "Never paste/share:", "Then resumes:"):
            self.assertIn(label, rendered)
        self.assertIn("REQUIRED", rendered)
        self.assertIn("OPTIONAL", rendered)

    def test_pack_reports_server_not_run_without_claiming_readiness(self):
        rendered = self.render()
        self.assertIn("Server: **NOT_RUN", rendered)
        self.assertNotIn("Server: **READY;", rendered)

    def test_pack_renders_real_server_failures(self):
        rendered = self.render({"status": "NOT_READY", "failed_checks": ["database_backup"]})
        self.assertIn("NOT_READY", rendered)
        self.assertIn("database_backup", rendered)

    def test_unsafe_boundary_is_rejected(self):
        config = deepcopy(self.config)
        config["global_boundaries"]["live_trading_enabled"] = True
        with self.assertRaises(ValueError):
            MODULE.validate_config(config)

    def test_short_commit_is_rejected(self):
        with self.assertRaises(ValueError):
            MODULE.render_pack(
                self.config,
                self.manifest,
                self.preflight,
                commit="abc123",
                branch="feature",
            )

    def test_config_is_json_and_contains_no_secret_values(self):
        raw = (ROOT / "webui-control" / "morning-human-actions.json").read_text(encoding="utf-8")
        json.loads(raw)
        forbidden = ("BEGIN OPENSSH PRIVATE KEY", "sk-", "Bearer ", "Basic ")
        for marker in forbidden:
            self.assertNotIn(marker, raw)


if __name__ == "__main__":
    unittest.main()

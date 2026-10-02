import json
import tempfile
import unittest
from pathlib import Path

from scripts.run_preopen_assurance import run_bundle


NOW = "2026-10-02T14:25:00Z"


class PreopenAssuranceBundleTests(unittest.TestCase):
    def test_missing_state_is_no_go_and_writes_inspectable_artifacts(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            runtime_path = root / "runtime.json"
            dashboard_path = root / "dashboard.json"
            gate_path = root / "gate.json"
            result = run_bundle(
                state_dir=root,
                bindings=root / "missing-bindings.json",
                acceptance_evidence=root / "missing-acceptance.json",
                runtime_output=runtime_path,
                dashboard_output=dashboard_path,
                gate_output=gate_path,
                generated_at=NOW,
                collect_runtime=lambda: {
                    "generated_at": NOW, "components": [], "artifacts": {}
                },
            )

            self.assertEqual(result["decision"], "NO_GO")
            self.assertGreater(result["counts"]["MISSING"], 0)
            self.assertEqual(result["side_effects"]["broker_calls"], 0)
            self.assertEqual(result["side_effects"]["order_actions"], 0)
            self.assertTrue(runtime_path.exists())
            self.assertTrue(dashboard_path.exists())
            self.assertTrue(gate_path.exists())
            self.assertEqual(json.loads(gate_path.read_text())["decision"], "NO_GO")

    def test_dashboard_validation_error_is_preserved_as_no_go(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "broker_fills.json").write_text(json.dumps({
                "environment": "LIVE", "broker_verified_fills": []
            }))
            result = run_bundle(
                state_dir=root,
                bindings=root / "missing-bindings.json",
                acceptance_evidence=root / "missing-acceptance.json",
                runtime_output=root / "runtime.json",
                dashboard_output=root / "dashboard.json",
                gate_output=root / "gate.json",
                generated_at=NOW,
                collect_runtime=lambda: {
                    "generated_at": NOW, "components": [], "artifacts": {}
                },
            )

            self.assertEqual(result["decision"], "NO_GO")
            self.assertIn("not DEMO", result["pipeline_error"])
            self.assertEqual(result["side_effects"]["provider_calls"], 0)


if __name__ == "__main__":
    unittest.main()

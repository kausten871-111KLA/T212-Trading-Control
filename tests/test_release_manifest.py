import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads(
    (ROOT / "webui-control" / "release-manifest.json").read_text(encoding="utf-8")
)


class ReleaseManifestTests(unittest.TestCase):
    def test_release_is_staged_with_no_live_effect(self):
        self.assertEqual(MANIFEST["release_state"], "STAGED_NOT_DEPLOYED")
        self.assertFalse(MANIFEST["live_effect"])

    def test_all_manifest_component_paths_exist(self):
        for component in MANIFEST["components"]:
            for key in ("config", "code"):
                relative = component.get(key)
                if relative:
                    self.assertTrue(
                        (ROOT / relative).is_file(),
                        f'{component["id"]} missing {key}: {relative}',
                    )

    def test_deployment_requires_tests_backup_and_human_approval(self):
        gates = MANIFEST["gates"]
        self.assertTrue(gates["require_clean_test_exit"])
        self.assertTrue(gates["require_backup_evidence_before_deploy"])
        self.assertTrue(gates["require_human_approval_before_deploy"])
        self.assertTrue(gates["forbid_secrets_in_repository"])

    def test_t212_remains_demo_only_and_fail_closed(self):
        safety = MANIFEST["trading_safety"]
        self.assertEqual(safety["environment"], "DEMO")
        self.assertFalse(safety["live_trading"])
        self.assertFalse(safety["order_mutation_during_control_plane_validation"])
        self.assertTrue(safety["fail_closed"])

    def test_rollback_preserves_audit_evidence(self):
        rollback = MANIFEST["rollback"]
        self.assertTrue(rollback["database_backup_required"])
        self.assertTrue(rollback["tool_table_backup_required"])
        self.assertTrue(rollback["preserve_audit_evidence"])


if __name__ == "__main__":
    unittest.main()

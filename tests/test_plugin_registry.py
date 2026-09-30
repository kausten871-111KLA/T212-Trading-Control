import copy
import json
import unittest
from pathlib import Path

from openwebui.tools.plugin_registry import (
    RegistryValidationError,
    connector_for,
    validate_registry,
)


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = json.loads(
    (ROOT / "webui-control" / "plugin-registry.json").read_text(encoding="utf-8")
)


class PluginRegistryTests(unittest.TestCase):
    def test_current_registry_is_valid(self):
        validate_registry(REGISTRY)

    def test_unregistered_connector_fails_closed(self):
        with self.assertRaises(PermissionError):
            connector_for(REGISTRY, "unknown-plugin", "apps-plugins-bots")

    def test_cross_workspace_access_is_denied(self):
        with self.assertRaises(PermissionError):
            connector_for(REGISTRY, "t212-demo-readiness", "books-publishing")

    def test_t212_live_enablement_is_rejected(self):
        changed = copy.deepcopy(REGISTRY)
        t212 = next(
            item for item in changed["connectors"]
            if item["id"] == "t212-demo-readiness"
        )
        t212["endpoint_policy"]["live_trading"] = True
        with self.assertRaises(RegistryValidationError):
            validate_registry(changed)

    def test_t212_order_mutation_is_rejected(self):
        changed = copy.deepcopy(REGISTRY)
        t212 = next(
            item for item in changed["connectors"]
            if item["id"] == "t212-demo-readiness"
        )
        t212["endpoint_policy"]["order_mutation"] = True
        with self.assertRaises(RegistryValidationError):
            validate_registry(changed)

    def test_unverified_source_is_rejected(self):
        changed = copy.deepcopy(REGISTRY)
        changed["connectors"][0]["source"]["verified"] = False
        with self.assertRaises(RegistryValidationError):
            validate_registry(changed)

    def test_secret_value_shape_is_rejected(self):
        changed = copy.deepcopy(REGISTRY)
        changed["connectors"][0]["secret_env"] = ["TOKEN=actual-value"]
        with self.assertRaises(RegistryValidationError):
            validate_registry(changed)


if __name__ == "__main__":
    unittest.main()

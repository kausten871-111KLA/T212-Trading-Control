"""Offline capability contract tests. No network, model, or broker requests."""
import unittest
from pathlib import Path
from deploy.deepseek.webui_tool_binding.automation_tool_contract import (
    assess_automation_tools, capability_manifest,
)

T212 = "trading_212_demo_gateway_tool"
ALPACA = "market_data_gateway"
TOOLS = {
    "trading_dashboard": {"tool_id": T212, "spec": {"name": "trading_dashboard"}},
    "list_positions": {"tool_id": T212, "spec": {"name": "list_positions"}},
    "snapshots": {"tool_id": ALPACA, "spec": {"name": "snapshots"}},
}

class TestWebUIAutomationToolContract(unittest.TestCase):
    def result(self, expected=None, requested=None, tools=None):
        return assess_automation_tools(
            [T212, ALPACA] if expected is None else expected,
            [T212, ALPACA] if requested is None else requested,
            TOOLS if tools is None else tools,
        )
    def test_both_tool_ids_resolve(self):
        result = self.result()
        self.assertTrue(result.ready)
        self.assertEqual(result.missing_ids, ())
    def test_dashboard_and_snapshots_manifest(self):
        value = capability_manifest(self.result())
        self.assertIn("trading_dashboard", value)
        self.assertIn("snapshots", value)
    def test_no_tool_calls_performed_by_contract(self):
        self.assertEqual(self.result().function_names, ("list_positions", "snapshots", "trading_dashboard"))
    def test_missing_t212_is_detected(self):
        result = self.result(tools={"snapshots": TOOLS["snapshots"]})
        self.assertEqual(result.missing_ids, (T212,))
    def test_missing_alpaca_is_detected(self):
        result = self.result(tools={"trading_dashboard": TOOLS["trading_dashboard"]})
        self.assertEqual(result.missing_ids, (ALPACA,))
    def test_zero_requested_tools_fails(self):
        self.assertFalse(self.result(requested=[]).ready)
    def test_partial_requested_tools_fails(self):
        self.assertEqual(self.result(requested=[ALPACA]).missing_ids, (T212,))
    def test_intentionally_tool_free_model(self):
        r = self.result(expected=[], requested=[], tools={})
        self.assertFalse(r.ready)
        self.assertEqual(r.missing_ids, ())
        self.assertIsNone(capability_manifest(r))
    def test_mcp_ids_are_separately_scoped(self):
        r = self.result(expected=[T212, ALPACA, "server:mcp:unavailable"])
        self.assertTrue(r.ready)
        self.assertNotIn("server:mcp:unavailable", r.expected_ids)
    def test_duplicate_ids_do_not_duplicate_receipts(self):
        r = self.result(expected=[T212, ALPACA, T212])
        self.assertEqual(len(r.expected_ids), 2)
    def test_missing_tool_id_field_does_not_satisfy_binding(self):
        r = self.result(tools={"trading_dashboard":{"spec":{"name":"trading_dashboard"}}, "snapshots":TOOLS["snapshots"]})
        self.assertEqual(r.missing_ids, (T212,))
    def test_manifest_never_includes_private_tool_payload_fields(self):
        r = self.result(tools={"trading_dashboard":{"tool_id":T212, "secret":"NOT_FOR_MODEL"},
                               "snapshots":{"tool_id":ALPACA, "secret":"NOT_FOR_MODEL"}})
        self.assertNotIn("NOT_FOR_MODEL",capability_manifest(r))
    def test_missing_bindings_produces_no_availability_manifest(self):
        self.assertIsNone(capability_manifest(self.result(tools={})))
    def test_artifact_patch_files_present(self):
        directory = Path(__file__).resolve().parents[1] / "deploy/deepseek/webui_tool_binding"
        self.assertIn("_resolve_model_defaults", (directory/"automations.patch").read_text())
        self.assertIn("capability_manifest", (directory/"middleware.patch").read_text())

if __name__=="__main__":
    unittest.main()

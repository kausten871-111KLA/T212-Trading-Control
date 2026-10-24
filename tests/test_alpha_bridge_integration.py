"""Alpha Vantage Contabo bridge contract tests: no provider/broker network."""
import ast
import unittest
from pathlib import Path
from unittest.mock import patch
from runtime.deepseek.host_command_bridge import COMMANDS, execute


class BridgeAlphaTests(unittest.TestCase):
    def test_command_is_allowlisted(self):
        self.assertIn("alpha_vantage_daily", COMMANDS)
        self.assertEqual(execute("arbitrary_shell")["error"], "unknown_command")

    def test_symbol_forwarding_to_provider_adapter(self):
        with patch("runtime.deepseek.alpha_vantage_data.daily_bars",
                   return_value={"ok": True, "symbol": "TSCO.LON", "is_intraday": False}) as stub:
            result = execute("alpha_vantage_daily", symbol="TSCO.LON")
        self.assertTrue(result["ok"])
        self.assertEqual(result["symbol"], "TSCO.LON")
        stub.assert_called_once_with("TSCO.LON")

    def test_bad_symbol_rejected_without_fetch(self):
        with patch("runtime.deepseek.alpha_vantage_data.urlopen",
                   side_effect=AssertionError("network must never be called")):
            result=execute("alpha_vantage_daily", symbol="IBM;cat /etc/passwd")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "invalid_symbol")

    def test_webui_tool_ast_contract_without_importing_live_db(self):
        p=(Path(__file__).resolve().parents[1]/"openwebui"/"tools"/"contabo_command_bridge.py")
        source=p.read_text()
        tree=ast.parse(source)
        methods=[n for cl in tree.body if isinstance(cl,ast.ClassDef) and cl.name=="Tools"
                 for n in cl.body if isinstance(n,ast.AsyncFunctionDef) and n.name=="contabo_command"]
        self.assertEqual(len(methods),1)
        self.assertIn("symbol",[arg.arg for arg in methods[0].args.args])
        self.assertIn("alpha_vantage_daily",source)
        self.assertNotIn("subprocess",source)


if __name__=="__main__":
    unittest.main()

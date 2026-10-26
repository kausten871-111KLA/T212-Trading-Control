"""Offline regressions for operator-supervised existing market gateway update."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / "deploy/deepseek/webui_tool_binding/v0124/market_insights_operator.py"
spec = importlib.util.spec_from_file_location("market_insights_operator_under_test", FILE)
operator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(operator)

BASE = (
    "import json\n"
    "class Tools:\n"
    "    async def candidate_scan(self, top=20, feed='iex'):\n"
    "        return '[]'\n"
)
ADDED = (
    "    async def market_insights_discovery(self):\n"
    "        result = await self.candidate_scan(top=20)\n"
    "        return {'orders_submitted_by_tool': 0, 'data': result}\n"
)


class OperatorCandidateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "candidate.py"
        self.path.write_text(BASE + "\n" + ADDED)
        self.patcher = patch.object(operator, "CANDIDATE", self.path)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.addCleanup(self.temp.cleanup)

    def test_exact_addition_preserves_prior_method(self):
        new = operator.new_content({"content": BASE})
        self.assertTrue(new.startswith(BASE.rstrip()))
        self.assertEqual(new.count("    async def market_insights_discovery("), 1)
        self.assertIn("async def candidate_scan", new)
        compile(new, "<test>", "exec")

    def test_previously_installed_function_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "already_installed"):
            operator.new_content({"content": BASE + ADDED})

    def test_any_live_source_drift_fails_closed(self):
        changed = BASE.replace("return '[]'", "return 'changed'")
        with self.assertRaisesRegex(RuntimeError, "existing_tool_differs"):
            operator.new_content({"content": changed})

    def test_unapproved_method_candidate_is_rejected(self):
        self.path.write_text(BASE + "\n" + ADDED.replace(
            "'orders_submitted_by_tool': 0", "'something_else': 1"))
        with self.assertRaisesRegex(RuntimeError, "unreviewed_discovery_method"):
            operator.new_content({"content": BASE})

    def test_no_candidate_rejected_without_touching_live_data(self):
        self.path.unlink()
        with self.assertRaisesRegex(RuntimeError, "candidate_source_not_staged"):
            operator.new_content({"content": BASE})


if __name__ == "__main__":
    unittest.main()

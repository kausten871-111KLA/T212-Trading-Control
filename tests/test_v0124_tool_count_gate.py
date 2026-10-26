"""Regression: both v0.12.4 acceptance paths must reject partial tool resolution.

These tests parse the exact production/staging acceptance sources without
importing WebUI, making provider calls, or touching Contabo.
"""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1] / "deploy/deepseek/webui_tool_binding/v0124"
SOURCES = [
    ROOT / "v0124_acceptance.py",
    ROOT / "run_isolated_db_acceptance.py",
]


def tool_count_guard(path):
    tree = ast.parse(path.read_text(), filename=str(path))
    guards = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert) and ast.unparse(node.test) == "len(got) >= 30":
            guards.append(node.test)
    if len(guards) != 1:
        raise AssertionError(f"{path.name}: expected exactly one 30-function assertion")
    return compile(ast.Expression(body=guards[0]), str(path), "eval")


class ToolResolutionCountGate(unittest.TestCase):
    def test_staging_and_production_reject_29_functions(self):
        for source in SOURCES:
            with self.subTest(source=source.name):
                code = tool_count_guard(source)
                self.assertFalse(eval(code, {"len": len}, {"got": list(range(29))}))

    def test_staging_and_production_accept_30_or_more_functions(self):
        for source in SOURCES:
            with self.subTest(source=source.name):
                code = tool_count_guard(source)
                self.assertTrue(eval(code, {"len": len}, {"got": list(range(30))}))
                self.assertTrue(eval(code, {"len": len}, {"got": list(range(35))}))


if __name__ == "__main__":
    unittest.main()

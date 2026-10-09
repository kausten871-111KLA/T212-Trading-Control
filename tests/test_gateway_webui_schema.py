"""Run in disposable official WebUI image: validates its real schema converter."""
import importlib.util
import unittest
import sys
from pathlib import Path

if Path("/app/backend").exists():
    sys.path.insert(0,"/app/backend")
try:
    from open_webui.utils.tools import get_tool_specs
except ModuleNotFoundError:
    get_tool_specs = None


@unittest.skipIf(get_tool_specs is None, "Requires official Open WebUI runtime")
class WebUISchemaTests(unittest.TestCase):
    def test_candidate_exposes_typed_execution_methods(self):
        source=Path(__file__).parents[1]/'openwebui/tools/trading212_demo_gateway_v03_selfcontained.py'
        spec=importlib.util.spec_from_file_location('schema_candidate',source)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        specs={s['name']:s for s in get_tool_specs(module.Tools())}
        for name in ['place_stop_order','place_limit_order','place_stop_limit_order','cancel_order','reconcile_order_intent','place_market_order','close_position','find_instrument']:
            self.assertIn(name,specs)
        for name in ['place_stop_order','place_limit_order','place_stop_limit_order','cancel_order']:
            self.assertIn('intent_id',specs[name]['parameters']['required'])
            self.assertEqual(specs[name]['parameters']['properties']['intent_id']['type'],'string')
        self.assertEqual(specs['cancel_order']['parameters']['properties']['order_id']['type'],'integer')
        self.assertEqual(specs['place_limit_order']['parameters']['properties']['quantity']['type'],'number')
        self.assertFalse(any(name.startswith('_') for name in specs))

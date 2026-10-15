
import importlib.util,json,sys
sys.path.insert(0,"/app/backend")
from pathlib import Path
from open_webui.utils.tools import get_tool_specs
source=Path('/workspace/openwebui/tools/trading212_demo_gateway.py')
spec=importlib.util.spec_from_file_location('integrated_candidate',source)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
schemas={row['name']:row for row in get_tool_specs(module.Tools())}
required={'trading_dashboard','find_instrument','list_positions','list_orders','place_market_order','close_position','place_stop_order','place_limit_order','place_stop_limit_order','cancel_order','reconcile_order_intent','place_market_order_with_intent','close_position_with_intent'}
assert required.issubset(schemas),(required-set(schemas))
for k in ['place_stop_order','place_limit_order','place_stop_limit_order','cancel_order']:
 assert 'intent_id' in schemas[k]['parameters']['required'],k
assert schemas['cancel_order']['parameters']['properties']['order_id']['type']=='integer'
assert len(schemas)==17; print('WEBUI_SCHEMA_ACCEPTANCE_PASS methods='+str(len(schemas))+' added=7')

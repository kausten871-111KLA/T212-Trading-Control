"""Exercise actual v0.2.3 gateway journal with a strictly fake transport."""
import json
import importlib.util
import socket
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from openwebui.tools.position_monitor_core import MonitorLedger, MonitorError
from openwebui.tools.position_monitor_gateway import DemoMonitorGateway

def forbidden_client(*args, **kwargs):
    raise AssertionError('HTTP transport forbidden in offline integration tests')


# Load the actual gateway source, substituting only its external HTTP client.
# Scope the stub to this import so other tests do not inherit fake dependencies.
source = Path(__file__).resolve().parents[1] / 'openwebui/tools/trading212_demo_gateway.py'
spec = importlib.util.spec_from_file_location('monitor_gateway_offline_reference', source)
gateway_module = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {'httpx': types.SimpleNamespace(AsyncClient=forbidden_client)}):
    spec.loader.exec_module(gateway_module)
Tools = gateway_module.Tools


class MonitorGatewayTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.calls = []
        self.order_state = 'FILLED'
        self.post_error = None
        self.positions_payload = [{'ticker': 'ACME_US_EQ', 'currentPrice': 90,
                                   'quantityAvailableForTrading': 2}]
        self.no_network = patch.object(socket.socket, 'connect', side_effect=AssertionError('Network forbidden'))
        self.no_network.start()
        self.addCleanup(self.no_network.stop)
        self.ledger = MonitorLedger(self.root / 'watches.sqlite')
        self.ledger.register('watch', 'ACME_US_EQ', 'AT_OR_BELOW', 95, 'intent-1', 'deepseek-v5')

    def gateway(self):
        tool = Tools()
        tool._metadata_cache.path = str(self.root / 'metadata.sqlite')
        tool._credentials = lambda: ('synthetic-test-key', 'synthetic-test-secret')
        async def transport(method, path, json_body=None):
            self.calls.append((method, path, json_body))
            if method == 'GET' and path == '/equity/positions':
                return self.positions_payload, None
            if method == 'GET' and path == '/equity/orders':
                return [], None
            if method == 'POST' and path == '/equity/orders/market':
                return (None, self.post_error) if self.post_error else ({'id': 123}, None)
            if method == 'GET' and path == '/equity/orders/123':
                return {'id': 123, 'status': self.order_state}, None
            raise AssertionError('Unexpected gateway route: ' + method + ' ' + path)
        tool._request = transport
        return tool

    def posts(self):
        return [row for row in self.calls if row[0] == 'POST']

    async def test_json_positions_reach_existing_durable_sell_method(self):
        outcome = await DemoMonitorGateway(self.gateway()).tick(self.ledger)
        self.assertEqual(outcome['submitted'], 1)
        self.assertEqual(self.posts()[0][2], {'ticker': 'ACME_US_EQ', 'quantity': -2.0, 'extendedHours': False})
        receipt = json.loads(self.ledger.rows(('FILLED',))[0]['broker_receipt'])
        self.assertEqual(receipt['intentId'], 'intent-1')
        self.assertEqual(receipt['brokerOrderId'], '123')
        self.assertFalse(receipt['liveTradingEnabled'])

    async def test_restart_reconciles_pending_order_without_second_post(self):
        self.order_state = 'NEW'
        await DemoMonitorGateway(self.gateway()).tick(self.ledger)
        self.assertEqual(len(self.ledger.rows(('ACKNOWLEDGED',))), 1)
        self.order_state = 'FILLED'
        restarted = MonitorLedger(self.root / 'watches.sqlite')
        result = await DemoMonitorGateway(self.gateway()).tick(restarted)
        self.assertEqual(result['reconciled'], 1)
        self.assertEqual(len(restarted.rows(('FILLED',))), 1)
        self.assertEqual(len(self.posts()), 1)

    async def test_timeout_remains_unknown_across_restart_without_second_post(self):
        self.post_error = 'synthetic timeout'
        await DemoMonitorGateway(self.gateway()).tick(self.ledger)
        restarted = MonitorLedger(self.root / 'watches.sqlite')
        await DemoMonitorGateway(self.gateway()).tick(restarted)
        self.assertEqual(len(restarted.rows(('UNKNOWN',))), 1)
        self.assertEqual(len(self.posts()), 1)

    async def test_crash_after_claim_before_journal_does_not_resubmit(self):
        self.ledger.claim('watch', 90)
        result = await DemoMonitorGateway(self.gateway()).tick(MonitorLedger(self.root / 'watches.sqlite'))
        self.assertEqual(result['reconciled'], 1)
        self.assertEqual(self.posts(), [])
        receipt = json.loads(self.ledger.rows(('UNKNOWN',))[0]['broker_receipt'])
        self.assertEqual(receipt['reason'], 'gateway_not_found')

    async def test_gateway_scope_changed_after_binding_never_called(self):
        tool = self.gateway()
        adapter = DemoMonitorGateway(tool)
        tool.base_url = 'https://live.trading212.com/api/v0'
        result = await adapter.tick(self.ledger)
        self.assertEqual(result['submitted'], 0)
        self.assertEqual(self.calls, [])

    async def test_non_demo_gateway_rejected_at_binding(self):
        tool = self.gateway()
        tool.base_url = 'https://live.trading212.com/api/v0'
        with self.assertRaises(MonitorError):
            DemoMonitorGateway(tool)
        self.assertEqual(self.calls, [])

    async def test_legacy_gateway_without_durable_method_rejected(self):
        tool = self.gateway()
        tool.place_market_order_with_intent = None
        with self.assertRaises(MonitorError):
            DemoMonitorGateway(tool)

    async def test_plain_text_gateway_error_is_not_empty_positions(self):
        tool = self.gateway()
        async def failure():
            return 'synthetic pacing error'
        tool.list_positions = failure
        outcome = await DemoMonitorGateway(tool).tick(self.ledger)
        self.assertEqual(outcome['submitted'], 0)
        self.assertEqual(outcome['unavailable'][0]['reason'], 'MonitorError')
        self.assertEqual(len(self.ledger.rows()), 1)

    async def test_json_error_object_cannot_be_positions(self):
        tool = self.gateway()
        async def failure():
            return '{"error":"synthetic error"}'
        tool.list_positions = failure
        outcome = await DemoMonitorGateway(tool).tick(self.ledger)
        self.assertEqual(outcome['submitted'], 0)
        self.assertEqual(len(outcome['unavailable']), 1)

    async def test_wrong_intent_receipt_is_not_success(self):
        tool = self.gateway()
        async def wrong_receipt(**kwargs):
            return json.dumps({'state': 'FILLED', 'intentId': 'different-intent',
                               'environment': 'DEMO', 'liveTradingEnabled': False})
        tool.place_market_order_with_intent = wrong_receipt
        await DemoMonitorGateway(tool).tick(self.ledger)
        self.assertEqual(len(self.ledger.rows(('UNKNOWN',))), 1)
        self.assertEqual(self.ledger.rows(('FILLED',)), [])

    async def test_receipt_with_live_marker_cannot_finalize_watch(self):
        self.ledger.claim('watch', 90)
        tool = self.gateway()
        async def wrong_receipt(intent):
            return {'state': 'FILLED', 'intentId': intent, 'environment': 'LIVE', 'liveTradingEnabled': True}
        tool.reconcile_order_intent = wrong_receipt
        outcome = await DemoMonitorGateway(tool).tick(self.ledger)
        self.assertEqual(outcome['reconciled'], 0)
        self.assertEqual(len(self.ledger.rows(('CLAIMED',))), 1)
        self.assertEqual(self.posts(), [])


if __name__ == '__main__':
    unittest.main()

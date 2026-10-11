import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    # This suite uses fake _request only. A missing optional HTTP dependency is
    # replaced solely during import; any accidental HTTP client construction fails.
    try:
        import httpx
        spec.loader.exec_module(module)
    except ModuleNotFoundError as exc:
        if exc.name != 'httpx':
            raise
        unavailable = types.ModuleType('httpx')
        def forbidden(*args, **kwargs):
            raise AssertionError('No HTTP transport permitted in this offline suite')
        unavailable.AsyncClient = forbidden
        with patch.dict(sys.modules, {'httpx': unavailable}):
            spec.loader.exec_module(module)
    return module


G = load(ROOT/'openwebui/tools/trading212_demo_gateway_v03_selfcontained.py', 'guarded_tool')
P = load(ROOT/'openwebui/trading212_demo_execution.py', 'guarded_pipe')


class Boundary(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.calls = []

    def tool(self, cls=G.Tools):
        t = cls()
        t._credentials = lambda: ('synthetic', 'synthetic')
        t.instrument_cache = G.InstrumentCache(self.temp.name+'/cache.json', self.temp.name+'/diff.json')
        async def request(method, path, json_body=None):
            self.calls.append((method, path, json_body))
            if path == '/equity/positions':
                return [{'ticker':'ACME_US_EQ','quantity':10,'quantityAvailableForTrading':10}], None
            if path == '/equity/orders':
                return [], None
            return {'id':123,'status':'PENDING'}, None
        t._request = request
        return t

    async def test_every_buy_type_rejects_before_transport(self):
        for cls in (G.Tools, P.Pipe):
            t = self.tool(cls)
            operations = (
                t.place_market_order('BUY','ACME_US_EQ',.1,intent_id='market'),
                t.place_limit_order('BUY','ACME_US_EQ',.1,5,'limit'),
                t.place_stop_order('BUY','ACME_US_EQ',.1,5,'stop'),
                t.place_stop_limit_order('BUY','ACME_US_EQ',.1,5,5,'stoplimit'),
            )
            for operation in operations:
                value = json.loads(await operation)
                self.assertEqual(value['state'], 'VALIDATION_FAILED')
                self.assertIn('RISK_ADMISSION_UNAVAILABLE', value['error'])
                self.assertFalse(value['mutationAttempted'])
        self.assertEqual(self.calls, [])

    async def test_pipe_command_cannot_bypass_admission(self):
        for command in ('BUY ACME_US_EQ 0.1', 'BUY EXT ACME_US_EQ 0.1 INTENT new-decision'):
            value = json.loads(await self.tool(P.Pipe).pipe({'messages':[{'content':command}]}))
            self.assertIn('RISK_ADMISSION_UNAVAILABLE', value['error'])
        self.assertEqual(self.calls, [])

    async def test_direct_private_boundary_rejects_buy(self):
        value = json.loads(await self.tool()._durable_mutation('direct','POST','/equity/orders/market',{'ticker':'ACME_US_EQ','quantity':1}))
        self.assertEqual(sum(c[0]=='POST' for c in self.calls),0)
        self.assertFalse(value['mutationAttempted'])
        self.assertEqual(self.calls, [])

    async def test_malformed_private_mutations_never_reach_transport(self):
        for quantity in (0, True, float('nan'), float('inf'), '1', None):
            value=json.loads(await self.tool()._durable_mutation('invalid','POST','/equity/orders/market',{'ticker':'ACME_US_EQ','quantity':quantity}))
            self.assertEqual(value['state'],'VALIDATION_FAILED')
        for method,path in (('PATCH','/equity/orders/1'),('POST','/other'),('DELETE','/equity/orders/not-an-id')):
            value=json.loads(await self.tool()._durable_mutation('invalid',method,path,{'ticker':'ACME_US_EQ','quantity':-1}))
            self.assertEqual(value['state'],'VALIDATION_FAILED')
        self.assertEqual(self.calls, [])

    async def test_unknown_sell_reloads_without_resubmission(self):
        first=self.tool()
        original=first._request
        async def lost_response(method,path,json_body=None):
            if method=='POST':
                self.calls.append((method,path,json_body))
                return None,'synthetic response lost'
            return await original(method,path,json_body)
        first._request=lost_response
        with patch.object(G.OrderIntentJournal,'pace',new=AsyncMock()):
            result=json.loads(await first.place_limit_order('SELL','ACME_US_EQ',1,5,'unknown-sell'))
            replay=json.loads(await self.tool().place_limit_order('SELL','ACME_US_EQ',1,5,'unknown-sell'))
        self.assertEqual(result['state'],'UNKNOWN')
        self.assertEqual(replay['state'],'UNKNOWN')
        self.assertTrue(replay['replayBlocked'])
        self.assertEqual(sum(call[0]=='POST' for call in self.calls),1)

    async def test_sell_reservation_still_prevents_overcommit(self):
        with patch.object(G.OrderIntentJournal, 'pace', new=AsyncMock()):
            first = json.loads(await self.tool().place_limit_order('SELL','ACME_US_EQ',6,5,'sell-first'))
            second = json.loads(await self.tool().place_stop_order('SELL','ACME_US_EQ',6,5,'sell-second'))
        self.assertEqual(first['state'],'PENDING')
        self.assertEqual(second['state'],'VALIDATION_FAILED')
        self.assertEqual(sum(c[0]=='POST' for c in self.calls),1)

    async def test_close_can_reduce_verified_holdings(self):
        value=json.loads(await self.tool().close_position('ACME_US_EQ','close'))
        self.assertEqual(value['state'],'PENDING')
        self.assertEqual([c for c in self.calls if c[0]=='POST'][0][2]['quantity'],-10)

    async def test_live_base_refused_before_transport(self):
        t=self.tool();t.base_url='https://live.trading212.com/api/v0'
        value=json.loads(await t.place_limit_order('BUY','ACME_US_EQ',1,5,'live'))
        self.assertFalse(value['mutationAttempted'])
        self.assertEqual(self.calls, [])

    async def test_dashboard_does_not_claim_buy_execution_enabled(self):
        value=json.loads(await self.tool(P.Pipe).pipe({'messages':[{'content':'DASHBOARD'}]}))
        self.assertFalse(value['riskIncreasingExecutionEnabled'])
        self.assertFalse(value['executionEnabled'])

    def test_pipe_is_exactly_generated(self):
        spec=importlib.util.spec_from_file_location('builder',ROOT/'scripts/build_t212_demo_pipe.py')
        builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
        self.assertEqual((ROOT/'openwebui/trading212_demo_execution.py').read_text(),builder.render(ROOT))


if __name__ == '__main__':
    unittest.main(verbosity=2)

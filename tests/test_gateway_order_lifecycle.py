import asyncio
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

MODULE = Path(__file__).parents[1] / 'openwebui/tools/trading212_demo_gateway_v03_selfcontained.py'
SPEC = importlib.util.spec_from_file_location('order_gateway', MODULE)
G = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(G)


class OrderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.calls = []
        self.status = 'PENDING'

    def tool(self):
        t = G.Tools()
        t._credentials = lambda: ('synthetic-account', 'synthetic-secret')
        t.instrument_cache = G.InstrumentCache(str(Path(self.temp.name)/'cache.json'), str(Path(self.temp.name)/'diff.json'))
        async def request(method, path, json_body=None):
            self.calls.append((method, path, json_body))
            if path == '/equity/positions':
                return [{'ticker':'ACME_US_EQ','quantity':10,'quantityAvailableForTrading':10}], None
            if path == '/equity/orders':
                return [], None
            if method == 'POST':
                return {'id':123,'status':'LOCAL'}, None
            if method == 'DELETE':
                return '', None
            return {'id':123,'status':self.status}, None
        t._request = request
        return t

    async def test_payloads_fractional_buy_sell_all_three_types(self):
        for kind in ['stop','limit','stop_limit']:
            for side in ['BUY','SELL']:
                with self.subTest(kind=kind, side=side):
                    t=self.tool();t.instrument_cache.cache_path=Path(self.temp.name)/(kind+side)/'cache.json'
                    args={'side':side,'ticker':'ACME_US_EQ','quantity':.25,'intent_id':kind+side,'time_validity':'GOOD_TILL_CANCEL'}
                    if kind!='limit':args['stop_price']=9.5
                    if kind!='stop':args['limit_price']=9.4
                    value=json.loads(await getattr(t,'place_'+kind+'_order')(**args))
                    post=[c for c in self.calls if c[0]=='POST'][-1]
                    self.assertEqual(post[1],'/equity/orders/'+kind)
                    self.assertEqual(post[2]['quantity'],.25 if side=='BUY' else -.25)
                    self.assertEqual(post[2]['timeValidity'],'GOOD_TILL_CANCEL')
                    self.assertEqual(value['state'],'PENDING')
                    self.assertTrue(value['verificationRequired'])

    async def test_invalid_quantity_and_prices_never_send(self):
        t=self.tool()
        for value in [None,0,-1,float('nan'),float('inf'),True]:
            for field in ['quantity','limit_price']:
                args=dict(side='BUY',ticker='ACME_US_EQ',quantity=1,limit_price=5,intent_id='invalid')
                args[field]=value
                self.assertEqual(json.loads(await t.place_limit_order(**args))['state'],'VALIDATION_FAILED')
        for args in [dict(side='SHORT'),dict(ticker=''),dict(time_validity='FOREVER')]:
            values=dict(side='BUY',ticker='ACME_US_EQ',quantity=1,limit_price=5,intent_id='bad');values.update(args)
            self.assertEqual(json.loads(await t.place_limit_order(**values))['state'],'VALIDATION_FAILED')
        self.assertEqual(self.calls,[])

    async def test_timeout_stays_unknown_and_restart_never_reposts(self):
        t=self.tool()
        async def timeout(method,path,json_body=None):
            self.calls.append((method,path,json_body));return None,'Timeout after transmission'
        t._request=timeout
        value=json.loads(await t.place_limit_order('BUY','ACME_US_EQ',.1,5,'timeout'))
        self.assertEqual(value['state'],'UNKNOWN')
        again=json.loads(await self.tool().place_limit_order('BUY','ACME_US_EQ',.1,5,'timeout'))
        self.assertTrue(again['replayBlocked']);self.assertEqual(len(self.calls),1)

    async def test_concurrent_instances_submit_once(self):
        values=await asyncio.wait_for(asyncio.gather(*(self.tool().place_limit_order('BUY','ACME_US_EQ',.1,5,'shared') for _ in range(5))),timeout=5)
        self.assertEqual(sum(c[0]=='POST' for c in self.calls),1)
        self.assertEqual(sum(json.loads(v).get('replayBlocked',False) for v in values),4)

    async def test_intent_payload_change_blocked(self):
        t=self.tool();await t.place_limit_order('BUY','ACME_US_EQ',.1,5,'identity')
        value=json.loads(await t.place_limit_order('BUY','ACME_US_EQ',.2,5,'identity'))
        self.assertEqual(value['state'],'VALIDATION_FAILED');self.assertEqual(sum(c[0]=='POST' for c in self.calls),1)

    async def test_cancel_fill_race_is_filled_not_cancelled(self):
        t=self.tool();original=t._request
        async def request(method,path,json_body=None):
            if method=='DELETE':self.status='FILLED'
            return await original(method,path,json_body)
        t._request=request
        value=json.loads(await t.cancel_order(123,'cancel'))
        self.assertEqual(value['state'],'FILLED');self.assertFalse(value['verificationRequired'])
        self.assertEqual(sum(c[0]=='DELETE' for c in self.calls),1)

    async def test_cancel_missing_readback_is_unknown(self):
        t=self.tool();original=t._request;deleted=False
        async def request(method,path,json_body=None):
            nonlocal deleted
            if method=='DELETE':deleted=True
            elif deleted:return None,'404 is not final broker proof'
            return await original(method,path,json_body)
        t._request=request
        self.assertEqual(json.loads(await t.cancel_order(123,'missing'))['state'],'UNKNOWN')

    async def test_terminal_and_partial_status_readbacks(self):
        for status in ['PARTIALLY_FILLED','FILLED','REJECTED','EXPIRED']:
            t=self.tool();t.instrument_cache.cache_path=Path(self.temp.name)/status/'cache.json';self.status=status
            value=json.loads(await t.place_stop_order('BUY','ACME_US_EQ',.1,5,status))
            self.assertEqual(value['state'],status)
            self.assertEqual(value['verificationRequired'],status not in G.OrderIntentJournal.TERMINAL)

    async def test_sell_cannot_exceed_holdings(self):
        t=self.tool()
        value=json.loads(await t.place_stop_order('SELL','ACME_US_EQ',11,5,'excess'))
        self.assertEqual(value['state'],'VALIDATION_FAILED');self.assertFalse(any(c[0]=='POST' for c in self.calls))

    async def test_unknown_sell_reservation_prevents_second_overcommit(self):
        t=self.tool();original=t._request
        async def request(method,path,json_body=None):
            if method=='POST':self.calls.append((method,path,json_body));return None,'timeout'
            return await original(method,path,json_body)
        t._request=request
        self.assertEqual(json.loads(await t.place_stop_order('SELL','ACME_US_EQ',6,5,'first'))['state'],'UNKNOWN')
        self.assertEqual(json.loads(await self.tool().place_stop_order('SELL','ACME_US_EQ',6,5,'second'))['state'],'VALIDATION_FAILED')
        self.assertEqual(sum(c[0]=='POST' for c in self.calls),1)

    async def test_legacy_market_fractional_operation_retained(self):
        value=json.loads(await self.tool().place_market_order('BUY','ACME_US_EQ',.1))
        self.assertEqual(value['quantity'],.1);self.assertEqual([c for c in self.calls if c[0]=='POST'][-1][1],'/equity/orders/market')

    async def test_market_compatibility_key_blocks_restart_replay(self):
        first=json.loads(await self.tool().place_market_order('BUY','ACME_US_EQ',.1))
        second=json.loads(await self.tool().place_market_order('BUY','ACME_US_EQ',.1))
        self.assertEqual(first['state'],'PENDING')
        self.assertTrue(second['replayBlocked'])
        self.assertEqual(sum(c[0]=='POST' for c in self.calls),1)

    async def test_market_explicit_decisions_share_sell_reservations(self):
        with mock.patch.object(G.OrderIntentJournal,'pace',new=mock.AsyncMock()):
            first=json.loads(await self.tool().place_market_order('SELL','ACME_US_EQ',6,intent_id='market-sell'))
            second=json.loads(await self.tool().place_limit_order('SELL','ACME_US_EQ',6,5,'pending-sell'))
        self.assertEqual(first['state'],'PENDING');self.assertEqual(second['state'],'VALIDATION_FAILED')
        self.assertEqual(sum(c[0]=='POST' for c in self.calls),1)

    async def test_market_invalid_values_never_send(self):
        for quantity in [None,True,float('nan'),float('inf'),0,-1]:
            self.assertEqual(json.loads(await self.tool().place_market_order('BUY','ACME_US_EQ',quantity))['state'],'VALIDATION_FAILED')
        self.assertEqual(json.loads(await self.tool().place_market_order('BUY','ACME_US_EQ',1,extended_hours='false'))['state'],'VALIDATION_FAILED')
        self.assertEqual(self.calls,[])

    async def test_close_position_uses_durable_market_intent(self):
        first=json.loads(await self.tool().close_position('ACME_US_EQ','close-decision'))
        second=json.loads(await self.tool().close_position('ACME_US_EQ','close-decision'))
        self.assertEqual(first['quantity'],10)
        self.assertTrue(second['replayBlocked'])
        self.assertEqual(sum(c[0]=='POST' for c in self.calls),1)

    async def test_already_terminal_cancel_readback_releases_reservation_without_delete(self):
        t=self.tool()
        with mock.patch.object(G.OrderIntentJournal,'pace',new=mock.AsyncMock()):
            await t.place_stop_order('SELL','ACME_US_EQ',6,5,'original')
            self.status='CANCELLED'
            result=json.loads(await t.cancel_order(123,'already-cancelled'))
            self.assertFalse(result['mutationAttempted'])
            self.assertFalse(any(c[0]=='DELETE' for c in self.calls))
            self.status='PENDING'
            result=json.loads(await t.place_limit_order('SELL','ACME_US_EQ',6,5,'replacement'))
        self.assertEqual(result['state'],'PENDING')

    async def test_confirmed_cancellation_releases_original_sell_reservation(self):
        t=self.tool()
        with mock.patch.object(G.OrderIntentJournal,'pace',new=mock.AsyncMock()):
            await t.place_stop_order('SELL','ACME_US_EQ',6,5,'protect')
            original=t._request
            async def request(method,path,json_body=None):
                if method=='DELETE':self.status='CANCELLED'
                return await original(method,path,json_body)
            t._request=request
            value=json.loads(await t.cancel_order(123,'cancel-protect'))
            self.assertEqual(value['state'],'CANCELLED')
            self.status='PENDING'
            value=json.loads(await t.place_limit_order('SELL','ACME_US_EQ',10,5,'replacement'))
            self.assertEqual(value['state'],'PENDING')

    async def test_unknown_reconciliation_never_submits(self):
        t=self.tool()
        async def timeout(method,path,json_body=None):return None,'timeout'
        t._request=timeout
        await t.place_stop_order('BUY','ACME_US_EQ',1,5,'ambiguous')
        t=self.tool();value=json.loads(await t.reconcile_order_intent('ambiguous'))
        self.assertEqual(value['state'],'UNKNOWN');self.assertFalse(value['retryAllowed']);self.assertEqual(self.calls,[])

    async def test_live_base_refused_before_http(self):
        t=G.Tools();t.base_url='https://live.trading212.com/api/v0'
        data,error=await t._request('POST','/equity/orders/stop',{})
        self.assertIsNone(data);self.assertIn('DEMO',error)

    async def test_actual_transport_mutations_are_never_retried(self):
        import httpx
        for code in [408,429,500]:
            calls=[]
            def handler(request):calls.append(request);return httpx.Response(code,json={'error':'synthetic'})
            real=httpx.AsyncClient
            def client(**kwargs):return real(transport=httpx.MockTransport(handler),**kwargs)
            t=G.Tools();t._credentials=lambda:('synthetic','synthetic')
            with mock.patch.object(G.httpx,'AsyncClient',side_effect=client):
                _,error=await t._request('POST','/equity/orders/stop',{'quantity':1})
            self.assertTrue(error);self.assertEqual(len(calls),1)

    async def test_metadata_429_waits_full_budget_and_http_date_is_supported(self):
        import httpx
        calls=[]
        def handler(request):
            calls.append(request)
            return httpx.Response(429 if len(calls)==1 else 200,json=[])
        real=httpx.AsyncClient
        def client(**kwargs):return real(transport=httpx.MockTransport(handler),**kwargs)
        t=G.Tools();t._credentials=lambda:('synthetic','synthetic')
        with mock.patch.object(G.httpx,'AsyncClient',side_effect=client):
            with mock.patch.object(G.asyncio,'sleep',new=mock.AsyncMock()) as sleep:
                await t._request('GET','/equity/metadata/instruments')
                sleep.assert_awaited_once_with(50.0)
        response=httpx.Response(429,headers={'Retry-After':'Fri, 09 Oct 2026 18:00:50 GMT'})
        with mock.patch.object(G.time,'time',return_value=1791568800):
            self.assertEqual(t._retry_delay(response,0),50.0)

    async def test_separate_process_crash_before_response_blocks_replay(self):
        child=r'''import asyncio,importlib.util,os,sys
from pathlib import Path
s=importlib.util.spec_from_file_location('g',sys.argv[1]);g=importlib.util.module_from_spec(s);s.loader.exec_module(g)
t=g.Tools();t._credentials=lambda:('synthetic-account','synthetic-secret')
t.instrument_cache=g.InstrumentCache(str(Path(sys.argv[2])/'cache.json'),str(Path(sys.argv[2])/'diff.json'))
async def crash(method,path,json_body=None):os._exit(33)
t._request=crash
asyncio.run(t.place_limit_order('BUY','ACME_US_EQ',.1,5,'crash'))
'''
        r=await asyncio.to_thread(subprocess.run,[sys.executable,'-c',child,str(MODULE),self.temp.name],capture_output=True)
        self.assertEqual(r.returncode,33)
        value=json.loads(await self.tool().place_limit_order('BUY','ACME_US_EQ',.1,5,'crash'))
        self.assertEqual(value['state'],'UNKNOWN');self.assertTrue(value['replayBlocked']);self.assertEqual(self.calls,[])

    async def test_two_operating_system_processes_submit_one_intent_once(self):
        child=r'''import asyncio,importlib.util,sys
from pathlib import Path
s=importlib.util.spec_from_file_location('g',sys.argv[1]);g=importlib.util.module_from_spec(s);s.loader.exec_module(g)
root=Path(sys.argv[2]);t=g.Tools();t._credentials=lambda:('synthetic-account','synthetic-secret')
t.instrument_cache=g.InstrumentCache(str(root/'cache.json'),str(root/'diff.json'))
async def request(method,path,json_body=None):
 if method=='POST':
  with (root/'mutations.txt').open('a') as f:f.write('POST\n')
  await asyncio.sleep(.1)
  return {'id':123},None
 return {'id':123,'status':'PENDING'},None
t._request=request
asyncio.run(t.place_limit_order('BUY','ACME_US_EQ',.1,5,'two-process'))
'''
        args=[sys.executable,'-c',child,str(MODULE),self.temp.name]
        a,b=await asyncio.gather(*(asyncio.to_thread(subprocess.run,args,capture_output=True) for _ in range(2)))
        self.assertEqual((a.returncode,b.returncode),(0,0))
        self.assertEqual((Path(self.temp.name)/'mutations.txt').read_text().splitlines(),['POST'])


if __name__=='__main__':unittest.main()

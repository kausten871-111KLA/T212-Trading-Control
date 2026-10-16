import asyncio
import json
import unittest
from runtime.deepseek.gateway_adapter import ExistingDemoGateway

class FakeGateway:
    base_url='https://demo.trading212.com/api/v0'
    def __init__(self): self.calls=[]
    def __getattr__(self, name):
        async def call(**kwargs):
            self.calls.append((name,kwargs))
            return json.dumps({'intentId':kwargs.get('intent_id'), 'environment':'DEMO',
                'liveTradingEnabled':False,'state':'PENDING','brokerOrderId':'123',
                'brokerResponse':{'id':123,'status':'PENDING'}})
        return call

class GatewaySeamTests(unittest.TestCase):
    def test_market_preserves_intent_and_uses_existing_method(self):
        gateway=FakeGateway();adapter=ExistingDemoGateway(gateway)
        result=adapter.place_market('stable-id','ACME_US_EQ','BUY',2)
        self.assertEqual(gateway.calls,[('place_market_order_with_intent',{'intent_id':'stable-id','ticker':'ACME_US_EQ','side':'BUY','quantity':2})])
        self.assertEqual(result.status,'PENDING');self.assertEqual(result.broker_order_id,123)
        self.assertEqual(result.receipt['brokerResponse']['status'],'PENDING')
    def test_protective_methods_and_cancel(self):
        gateway=FakeGateway();adapter=ExistingDemoGateway(gateway)
        adapter.place_limit('a','ACME','BUY',2,10)
        adapter.place_stop('b','ACME','SELL',2,8)
        adapter.place_stop_limit('c','ACME','SELL',2,8,7)
        adapter.cancel('d',123)
        self.assertEqual([c[0] for c in gateway.calls],['place_limit_order','place_stop_order','place_stop_limit_order','cancel_order'])
        self.assertEqual(gateway.calls[2][1]['stop_price'],8)
        self.assertEqual(gateway.calls[2][1]['limit_price'],7)
    def test_live_endpoint_change_rejected_before_call(self):
        gateway=FakeGateway();adapter=ExistingDemoGateway(gateway)
        gateway.base_url='https://live.trading212.com/api/v0'
        with self.assertRaises(ValueError):adapter.place_market('i','ACME','BUY',1)
        self.assertEqual(gateway.calls,[])
    def test_async_host_must_use_worker_thread(self):
        gateway=FakeGateway();adapter=ExistingDemoGateway(gateway)
        async def run():
            with self.assertRaises(RuntimeError):adapter.place_market('i','ACME','BUY',1)
        asyncio.run(run());self.assertEqual(gateway.calls,[])
    def test_reconcile_never_submits(self):
        gateway=FakeGateway();adapter=ExistingDemoGateway(gateway)
        self.assertEqual(adapter.reconcile('i')['status'],'PENDING')
        self.assertEqual(gateway.calls[0][0],'reconcile_order_intent')

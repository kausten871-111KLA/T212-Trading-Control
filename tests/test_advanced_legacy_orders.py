
import unittest, tempfile, pathlib, importlib.util, json, asyncio
root=pathlib.Path(__file__).parent
spec=importlib.util.spec_from_file_location('advanced_gateway',root/'../openwebui/tools/trading212_demo_gateway.py')
g=importlib.util.module_from_spec(spec); spec.loader.exec_module(g)

class AdvancedOrders(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.calls=[]
        self.status="PENDING"
    def tool(self):
        t=g.Tools()
        t._metadata_cache.path=str(pathlib.Path(self.tmp.name)/'metadata.sqlite3')
        t._credentials=lambda: ('synthetic-demo-key','synthetic-secret')
        async def request(method,path,json_body=None):
            self.calls.append((method,path,json_body))
            if method=='GET' and path=='/equity/positions':
                return [{'ticker':'ACME_US_EQ','quantity':10,'quantityAvailableForTrading':10}],None
            if method=='GET' and path=='/equity/orders':return [],None
            if method=='GET' and path.startswith('/equity/orders/'):
                return {'id':123,'status':self.status},None
            if method=='POST':return {'id':123,'status':'PENDING'},None
            if method=='DELETE':
                self.status='CANCELLED'
                return {},None
            return None,'unexpected test path'
        t._request=request
        return t
    async def test_stop_limit_stoplimit_payload(self):
        for kind in ('stop','limit','stop_limit'):
            t=self.tool()
            self.calls.clear()
            kw={'side':'SELL','ticker':'ACME_US_EQ','quantity':0.5,
               'intent_id':'order_'+kind,'time_validity':'GOOD_TILL_CANCEL'}
            if kind!='limit':kw['stop_price']=12.50
            if kind!='stop':kw['limit_price']=12.40
            result=json.loads(await getattr(t,'place_'+kind+'_order')(**kw))
            self.assertIn(result['state'],('PENDING','SUBMITTED'))
            posts=[row for row in self.calls if row[0]=='POST']
            self.assertEqual(posts[0][1],'/equity/orders/'+kind)
            self.assertEqual(posts[0][2]['quantity'],-0.5)
    async def test_same_intent_not_resubmitted_even_after_new_object(self):
        a=self.tool(); b=self.tool()
        req={'side':'BUY','ticker':'ACME_US_EQ','quantity':1,'limit_price':10,
             'intent_id':'same_id'}
        first=json.loads(await a.place_limit_order(**req))
        second=json.loads(await b.place_limit_order(**req))
        self.assertIn(first['state'],('PENDING','SUBMITTED'))
        self.assertTrue(second['replayBlocked'])
        self.assertEqual(sum(1 for op,path,_ in self.calls if op=='POST'),1)
    async def test_conflicting_intent_is_blocked(self):
        a=self.tool()
        await a.place_limit_order('BUY','ACME_US_EQ',1,10,'locked_id')
        second=json.loads(await a.place_limit_order('BUY','ACME_US_EQ',2,10,'locked_id'))
        self.assertEqual(second['state'],'VALIDATION_FAILED')
        self.assertEqual(sum(1 for op,path,_ in self.calls if op=='POST'),1)
    async def test_no_negative_nan_inf_payload(self):
        t=self.tool()
        for val in [float('nan'),float('inf'),-2,0,None]:
            res=json.loads(await t.place_limit_order('BUY','ACME_US_EQ',val,10,'invalid'))
            self.assertEqual(res['state'],'VALIDATION_FAILED')
        self.assertEqual(sum(1 for op,path,_ in self.calls if op=='POST'),0)
    async def test_cancel_readback(self):
        t=self.tool()
        self.status='PENDING'
        r=json.loads(await t.cancel_order(order_id=123,intent_id='cancel-1'))
        self.assertEqual(r['state'],'CANCELLED')
        self.assertEqual(len([x for x in self.calls if x[0]=='DELETE']),1)
    async def test_live_endpoint_refused(self):
        t=self.tool()
        t.base_url='https://live.trading212.com/api/v0'
        r=json.loads(await t.place_limit_order('BUY','ACME_US_EQ',1,12,'live-check'))
        self.assertEqual(r['state'],'VALIDATION_FAILED')
        self.assertEqual(len([x for x in self.calls if x[0]=='POST']),0)

if __name__=='__main__':unittest.main(verbosity=2)

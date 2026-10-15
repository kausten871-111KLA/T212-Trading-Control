
import importlib.util,json,tempfile,unittest
from pathlib import Path

MODULE=Path(__file__).resolve().parents[1]/"openwebui/tools/trading212_demo_gateway.py"
spec=importlib.util.spec_from_file_location("durable_market",MODULE)
G=importlib.util.module_from_spec(spec);spec.loader.exec_module(G)

class MarketIntentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.calls=[]
        self.post_error=None
        self.quantity=5
    def tool(self):
        t=G.Tools()
        t._metadata_cache.path=str(Path(self.tmp.name)/"cache.sqlite")
        t._credentials=lambda:("sample-demo-id","sample-demo-key")
        async def req(method,path,json_body=None):
            self.calls.append((method,path,json_body))
            if path=="/equity/positions":
                return [{"ticker":"ACME_US_EQ","quantity":self.quantity,
                         "quantityAvailableForTrading":self.quantity}],None
            if path=="/equity/orders":return [],None
            if method=="POST":
                return (None,self.post_error) if self.post_error else ({"id":101},None)
            if method=="GET" and path=="/equity/orders/101":
                return {"id":101,"status":"FILLED"},None
            return None,"Unexpected path"
        t._request=req
        return t
    async def test_buy_requires_stable_intent_and_verifies(self):
        t=self.tool()
        x=json.loads(await t.place_market_order_with_intent("BUY","ACME_US_EQ",0.7,"buy-dec-001"))
        self.assertEqual(x["state"],"FILLED")
        self.assertEqual(x["brokerOrderId"],"101")
        self.assertEqual([r[2]["quantity"] for r in self.calls if r[0]=="POST"],[0.7])
    async def test_reuse_never_reposts_across_instances(self):
        one=self.tool();two=self.tool()
        args=("BUY","ACME_US_EQ",1.0,"decision-a")
        await one.place_market_order_with_intent(*args)
        r=json.loads(await two.place_market_order_with_intent(*args))
        self.assertTrue(r["replayBlocked"])
        self.assertEqual(sum(1 for r in self.calls if r[0]=="POST"),1)
    async def test_different_intent_allows_new_market_decision(self):
        t=self.tool()
        await t.place_market_order_with_intent("BUY","ACME_US_EQ",0.5,"trade-1")
        await t.place_market_order_with_intent("BUY","ACME_US_EQ",0.5,"trade-2")
        self.assertEqual(sum(1 for r in self.calls if r[0]=="POST"),2)
    async def test_timeout_unknown_not_retried(self):
        t=self.tool();self.post_error="synthetic broker timeout"
        x=json.loads(await t.place_market_order_with_intent("BUY","ACME_US_EQ",1,"timeout-intent"))
        y=json.loads(await t.place_market_order_with_intent("BUY","ACME_US_EQ",1,"timeout-intent"))
        self.assertEqual(x["state"],"UNKNOWN")
        self.assertTrue(y["replayBlocked"])
        self.assertEqual(sum(1 for r in self.calls if r[0]=="POST"),1)
    async def test_verified_close_intent(self):
        t=self.tool();self.quantity=2.25
        x=json.loads(await t.close_position_with_intent("ACME_US_EQ","close-001"))
        self.assertEqual(x["state"],"FILLED")
        self.assertEqual([r[2]["quantity"] for r in self.calls if r[0]=="POST"],[-2.25])
    async def test_demo_only(self):
        t=self.tool();t.base_url="https://live.trading212.com/api/v0"
        r=json.loads(await t.place_market_order_with_intent("BUY","ACME_US_EQ",1,"live-refuse"))
        self.assertEqual(r["state"],"VALIDATION_FAILED")
        self.assertEqual(sum(1 for r in self.calls if r[0]=="POST"),0)

if __name__=="__main__":unittest.main(verbosity=2)

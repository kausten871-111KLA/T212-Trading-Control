"""Legacy 10-method gateway cache/backoff regressions; synthetic broker only."""
import asyncio
import multiprocessing
import importlib.util
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

SOURCE=Path(__file__).resolve().parents[1]/"openwebui/tools/trading212_demo_gateway.py"
spec=importlib.util.spec_from_file_location("t212_legacy_metadata_candidate",SOURCE)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

CATALOGUE=[
    {"ticker":"ACME_US_EQ","name":"ACME Holdings","currencyCode":"USD","type":"STOCK"},
    {"ticker":"SOME_UK_EQ","name":"Some Co","currencyCode":"GBP","type":"STOCK"}
]

def process_lookup(dbpath, counter):
    import os
    os.environ["T212_LEGACY_METADATA_CACHE_PATH"]=dbpath
    tool=module.Tools()
    tool._credentials=lambda:("same-test-account-key","synthetic")
    async def fake_request(method,path,json_body=None):
        with counter.get_lock():
            counter.value+=1
        await asyncio.sleep(0.15)
        return list(CATALOGUE),None
    tool._request=fake_request
    asyncio.run(tool.find_instrument("acme"))

class LegacyCache(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db=Path(self.temp.name)/"metadata.sqlite"
        self.calls=[]
        self.env=patch.dict("os.environ",{"T212_LEGACY_METADATA_CACHE_PATH":str(self.db)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def tool(self,key="key-A",response=None,sleep=0):
        t=module.Tools()
        t._credentials=lambda:(key,"synthetic-test-secret")
        async def request(method,path,json_body=None):
            self.calls.append((key,method,path,json_body))
            if sleep:await asyncio.sleep(sleep)
            if callable(response):return response(method,path,json_body)
            if response is not None:return response
            return list(CATALOGUE),None
        t._request=request
        return t

    def age(self,seconds=700,earliest=0):
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE metadata SET fetched=?,earliest=?,owner=NULL,lease_until=0",
                       (time.time()-seconds,earliest))

    async def test_fresh_cache_persists_across_instances_and_preserves_list_contract(self):
        a=json.loads(await self.tool().find_instrument("acme"))
        b=json.loads(await self.tool().find_instrument("acme"))
        self.assertEqual([x["ticker"] for x in a],["ACME_US_EQ"])
        self.assertEqual(a,b)
        self.assertEqual(len(self.calls),1)
        self.assertEqual(self.db.stat().st_mode & 0o777,0o600)

    async def test_concurrent_first_lookups_have_one_broker_get(self):
        tools=[self.tool(sleep=.08) for _ in range(4)]
        result=await asyncio.gather(*(t.find_instrument("acme") for t in tools))
        self.assertEqual(len(self.calls),1)
        self.assertEqual(sum(isinstance(json.loads(x),list) for x in result if x.startswith("[")),1)
        self.assertEqual(len(json.loads(await self.tool().find_instrument("acme"))),1)
        self.assertEqual(len(self.calls),1)

    async def test_four_processes_share_one_metadata_get(self):
        counter=multiprocessing.Value("i",0)
        children=[multiprocessing.Process(target=process_lookup,
                        args=(str(self.db),counter)) for _ in range(4)]
        for child in children:child.start()
        for child in children:
            child.join(10)
            self.assertFalse(child.is_alive())
            self.assertEqual(child.exitcode,0)
        self.assertEqual(counter.value,1)
        self.assertEqual(len(json.loads(await self.tool(key="same-test-account-key").find_instrument("acme"))),1)

    async def test_429_is_throttled_and_never_auto_retried(self):
        result=await self.tool(response=(None,"T212 DEMO API error 429 (Retry-After: 120): limit")).find_instrument("acme")
        self.assertIn("unavailable",result)
        result2=await self.tool(response=(None,"should not be called")).find_instrument("acme")
        self.assertIn("budget busy",result2)
        self.assertEqual(len(self.calls),1)
        with sqlite3.connect(self.db) as db:
            remaining=db.execute("SELECT earliest FROM metadata").fetchone()[0]-time.time()
        self.assertGreater(remaining,100)

    async def test_stale_cache_is_research_only_not_executable(self):
        await self.tool().find_instrument("acme")
        self.age(700,time.time()+45)
        value=json.loads(await self.tool().find_instrument("acme"))
        self.assertEqual(value["status"],"STALE_RESEARCH_ONLY")
        self.assertTrue(value["notExecutionVerified"])
        self.assertEqual(value["matches"][0]["ticker"],"ACME_US_EQ")
        self.assertEqual(len(self.calls),1)

    async def test_credential_scopes_are_isolated(self):
        await self.tool("key-A").find_instrument("acme")
        await self.tool("key-B").find_instrument("acme")
        self.assertEqual(len(self.calls),2)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM metadata").fetchone()[0],2)

    async def test_configured_account_scope_shared_across_keys(self):
        with patch.dict("os.environ", {"T212_DEMO_ACCOUNT_SCOPE":"same-demo-account"}):
            await self.tool("key-A").find_instrument("acme")
            await self.tool("key-B").find_instrument("acme")
        self.assertEqual(len(self.calls),1)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM metadata").fetchone()[0],1)

    async def test_fresh_broker_read_budget_is_persisted_by_route(self):
        cache=module._MetadataCache(str(self.db))
        scope="account-A"
        wait,allowed=cache.reserve_read(scope,"/equity/account/summary",5.5,100)
        self.assertEqual((wait,allowed),(0,True))
        wait,allowed=module._MetadataCache(str(self.db)).reserve_read(
            scope,"/equity/account/summary",5.5,100)
        self.assertGreaterEqual(wait,5)
        self.assertFalse(allowed)
        wait2,allowed2=cache.reserve_read(scope,"/equity/positions",1.25,100)
        self.assertEqual((wait2,allowed2),(0,True))
        cache.defer_read(scope,"/equity/account/summary",120)
        with sqlite3.connect(self.db) as db:
            future=db.execute("SELECT earliest FROM read_budget WHERE route=?",
                         ("/equity/account/summary",)).fetchone()[0]
        self.assertGreater(future,time.time()+100)

    async def test_actual_request_uses_pacing_and_returns_fresh_broker_data(self):
        sent=[]
        class FakeResponse:
            is_error=False
            status_code=200
            headers={}
            def json(self):return {"account":"synthetic-fresh"}
        class FakeClient:
            def __init__(self,**kwargs):pass
            async def __aenter__(self):return self
            async def __aexit__(self,*a):return False
            async def request(self,method,url,**kwargs):
                sent.append((method,url))
                return FakeResponse()
        t=module.Tools()
        t._credentials=lambda:("synthetic", "synthetic")
        with patch.object(module.httpx,"AsyncClient",FakeClient):
            first,error=await t._request("GET","/equity/account/summary")
            second,error2=await t._request("GET","/equity/account/summary")
            third,error3=await t._request("GET","/equity/orders")
        self.assertEqual(first,{"account":"synthetic-fresh"})
        self.assertIsNone(error)
        self.assertIsNone(second)
        self.assertIn("paced",error2)
        self.assertEqual(third,{"account":"synthetic-fresh"})
        self.assertIsNone(error3)
        self.assertEqual(len(sent),2)

    async def test_actual_http_429_header_persists_read_cooldown(self):
        sent=[]
        class FakeResponse:
            is_error=True
            status_code=429
            headers={"Retry-After":"120"}
            def json(self):return {"error":"synthetic throttle"}
        class FakeClient:
            def __init__(self,**kwargs):pass
            async def __aenter__(self):return self
            async def __aexit__(self,*a):return False
            async def request(self,method,url,**kwargs):
                sent.append((method,url))
                return FakeResponse()
        t=module.Tools()
        t._credentials=lambda:("synthetic","synthetic")
        with patch.object(module.httpx,"AsyncClient",FakeClient):
            first,error=await t._request("GET","/equity/orders")
            second,error2=await t._request("GET","/equity/orders")
        self.assertIsNone(first)
        self.assertIn("429",error)
        self.assertIn("120",error)
        self.assertIsNone(second)
        self.assertIn("paced",error2)
        self.assertEqual(len(sent),1)
        with sqlite3.connect(self.db) as db:
            remaining=db.execute("SELECT earliest FROM read_budget WHERE route=?",
                  ("/equity/orders",)).fetchone()[0]-time.time()
        self.assertGreater(remaining,100)

    async def test_corrupt_cache_fails_closed_without_clobbering(self):
        await self.tool().find_instrument("acme")
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE metadata SET payload='invalid-json'")
        out=await self.tool().find_instrument("acme")
        self.assertIn("cache unavailable",out)
        self.assertEqual(len(self.calls),1)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute("SELECT payload FROM metadata").fetchone()[0],"invalid-json")

    async def test_invalid_refresh_does_not_replace_last_valid_snapshot(self):
        await self.tool().find_instrument("acme")
        with sqlite3.connect(self.db) as db:
            original=db.execute("SELECT payload FROM metadata").fetchone()[0]
        self.age(700)
        result=await self.tool(response=([{"name":"no ticker"}],None)).find_instrument("acme")
        self.assertIn("persistence failed",result)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute("SELECT payload FROM metadata").fetchone()[0],original)
        self.assertEqual(len(self.calls),2)

    async def test_legacy_market_buy_sell_functions_not_replaced(self):
        posts=[]
        t=module.Tools()
        t._credentials=lambda:("synthetic","synthetic")
        async def fake_request(method,path,json_body=None):
            posts.append((method,path,json_body))
            return {"id":111,"status":"PENDING"},None
        t._request=fake_request
        result=json.loads(await t.place_market_order("BUY","ACME_US_EQ",0.5))
        result2=json.loads(await t.place_market_order("SELL","ACME_US_EQ",0.25))
        self.assertEqual([row[2]["quantity"] for row in posts],[0.5,-0.25])
        self.assertEqual(result["action"],"BUY")
        self.assertEqual(result2["action"],"SELL")
        self.assertTrue(result["verificationRequired"])

    async def test_original_method_surface_preserved_with_additions(self):
        import ast
        tree=ast.parse(SOURCE.read_text())
        cls=[x for x in tree.body if isinstance(x,ast.ClassDef) and x.name=="Tools"][0]
        methods=[x.name for x in cls.body if isinstance(x,(ast.FunctionDef,ast.AsyncFunctionDef))
                 and not x.name.startswith("_")]
        self.assertEqual(methods[:10],["trading_dashboard","find_instrument","recent_order_history",
              "recent_transactions","operations_dashboard","list_positions","list_orders",
              "size_quantity","place_market_order","close_position"])
        self.assertEqual(methods[10:],["place_stop_order","place_limit_order",
              "place_stop_limit_order","cancel_order","reconcile_order_intent",
              "place_market_order_with_intent","close_position_with_intent"])

if __name__=="__main__":
    unittest.main()

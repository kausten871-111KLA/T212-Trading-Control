import asyncio,importlib.util,tempfile,unittest
from pathlib import Path
P=Path(__file__).resolve().parents[1]/"openwebui/tools/position_monitor_core.py"
SPEC=importlib.util.spec_from_file_location("monitor_core",P)
M=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(M)

class MonitorCoreTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/"watches.sqlite"
        self.ledger=M.MonitorLedger(self.path)
        self.calls=[];self.price=100.0;self.qty=2.0
    def register(self,operator="AT_OR_BELOW",level=95,watch_id="watch-1",intent_id="intent-1"):
        return self.ledger.register(watch_id,"ACME_US_EQ",operator,level,intent_id,"deepseek-v5")
    async def tick(self,quote_present=True):
        async def positions():
            row={"ticker":"ACME_US_EQ","quantityAvailableForTrading":self.qty}
            if quote_present:row["currentPrice"]=self.price
            return [row]
        async def exit_submit(ticker,qty,intent):
            self.calls.append((ticker,qty,intent))
            return {"state":"FILLED","brokerOrderId":123,"verifiedBy":"synthetic-demo-broker"}
        async def reconcile(intent):
            return {"state":"FILLED","brokerOrderId":123}
        return await M.monitor_once(self.ledger,positions,exit_submit,reconcile)
    async def test_threshold_not_hit_no_order(self):
        self.register();self.price=97
        outcome=await self.tick()
        self.assertEqual(outcome["submitted"],0);self.assertEqual(self.calls,[])
    async def test_thesis_condition_hit_executes_once(self):
        self.register();self.price=94.5
        outcome=await self.tick()
        self.assertEqual(outcome["submitted"],1)
        self.assertEqual(self.calls,[("ACME_US_EQ",2.0,"intent-1")])
        self.assertEqual(self.ledger.rows(("FILLED",))[0]["state"],"FILLED")
        await self.tick()
        self.assertEqual(len(self.calls),1)
    async def test_above_trigger_is_also_supported(self):
        self.register(operator="AT_OR_ABOVE",level=115)
        self.price=116
        self.assertEqual((await self.tick())["submitted"],1)
    async def test_missing_price_does_not_fire(self):
        self.register();self.price=90
        result=await self.tick(quote_present=False)
        self.assertEqual(result["submitted"],0)
        self.assertEqual(len(result["unavailable"]),1)
    async def test_duplicate_registration_idempotent_conflict_rejected(self):
        self.assertEqual(self.register(),"REGISTERED")
        self.assertEqual(self.register(),"EXISTING")
        with self.assertRaises(M.MonitorError):self.register(level=70)
    async def test_one_claim_across_two_store_instances(self):
        self.register()
        other=M.MonitorLedger(self.path)
        self.assertTrue(self.ledger.claim("watch-1",90))
        self.assertFalse(other.claim("watch-1",90))
        self.assertEqual(len(self.ledger.rows(("CLAIMED",))),1)
    async def test_unknown_is_reconciled_not_reissued(self):
        self.register();self.assertTrue(self.ledger.claim("watch-1",90))
        self.ledger.record("watch-1","UNKNOWN",{"error":"synthetic timeout"})
        self.price=90
        result=await self.tick()
        self.assertEqual(result["reconciled"],1)
        self.assertEqual(len(self.calls),0)
        self.assertEqual(self.ledger.rows(("FILLED",))[0]["intent_id"],"intent-1")
    async def test_multiple_independent_watches_no_strategy_cap(self):
        self.register()
        self.register(watch_id="watch-2",intent_id="intent-2",level=92)
        self.price=90
        result=await self.tick()
        self.assertEqual(result["submitted"],2)
        self.assertEqual({c[2] for c in self.calls},{"intent-1","intent-2"})
        # Once live, the shared gateway journal will also check remaining SELL holdings.
    async def test_controller_can_cancel_and_reversion_watch(self):
        self.register()
        self.assertEqual(self.ledger.cancel_active("watch-1"),"CANCELLED")
        self.price=90
        self.assertEqual((await self.tick())["submitted"],0)
        self.assertEqual(self.register(watch_id="watch-2",intent_id="intent-2",level=89),"REGISTERED")
        self.price=88
        self.assertEqual((await self.tick())["submitted"],1)
        self.assertEqual(self.calls[0][2],"intent-2")

    async def test_reject_bad_values(self):
        for value in [0,-1,float("inf"),float("nan"),None]:
            with self.assertRaises(M.MonitorError):self.register(level=value)
        with self.assertRaises(M.MonitorError):
            self.ledger.register("watch_1","ACME_US_EQ","INVALID",10,"intent_1","v1")

if __name__=="__main__":unittest.main()

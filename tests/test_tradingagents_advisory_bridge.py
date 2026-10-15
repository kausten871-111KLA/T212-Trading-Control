import importlib.util
import unittest
from pathlib import Path

SOURCE=Path(__file__).resolve().parents[1]/"openwebui/tools/tradingagents_advisory_bridge.py"
spec=importlib.util.spec_from_file_location("ta_bridge",SOURCE)
bridge=importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)

class AdapterTests(unittest.TestCase):
    def test_normalises_reports_and_has_no_execution_authority(self):
        state={"market_report":"trend up","news_report":"earnings","final_trade_decision":"BUY",
               "messages":["ignore this"],"api_key":"SECRET_THAT_MUST_NOT_LEAK"}
        x=bridge.make_advisory("NVDA","2026-10-15",state,None,
                               upstream_revision="pinned-upstream",generated_at_utc="2026-10-15T17:00:00Z")
        self.assertFalse(x["execution_authority"])
        self.assertEqual(x["source"],"TauricResearch/TradingAgents")
        self.assertEqual(x["reports"]["market_report"],"trend up")
        self.assertNotIn("api_key",str(x))
        self.assertNotIn("SECRET_THAT_MUST_NOT_LEAK",str(x))
        self.assertEqual(x["trading212_broker_calls"],0)

    def test_evidence_id_deterministic_with_timestamp_changed(self):
        base={"news_report":"Company announced results."}
        a=bridge.make_advisory("MU","2026-10-15",base,"HOLD",generated_at_utc="date1")
        b=bridge.make_advisory("MU","2026-10-15",base,"HOLD",generated_at_utc="date2")
        self.assertEqual(a["advisory_id"],b["advisory_id"])
        self.assertNotEqual(a["generated_at_utc"],b["generated_at_utc"])

    def test_invalid_symbol_and_future_date_do_not_call_models(self):
        for symbol in ["MU && curl evil","../path","x y",""]:
            with self.assertRaises(bridge.AdvisoryError):
                bridge.make_advisory(symbol,"2026-10-15",{},None)
        with self.assertRaises(bridge.AdvisoryError):
            bridge.make_advisory("NVDA","2099-01-01",{},None)

    def test_mock_real_upstream_graph_interface(self):
        calls=[]
        class MockGraph:
            def __init__(self,**kwargs):calls.append(("construct",kwargs))
            def propagate(self,symbol,date):
                calls.append(("propagate",symbol,date))
                return {"market_report":"Momentum",
                        "news_report":"Catalyst",
                        "final_trade_decision":"BUY"}, "BUY"
        x=bridge.research_once("MU","2026-10-15",
                                selected_analysts=("market","news"),
                                config={"llm_provider":"deepseek"},
                                graph_factory=MockGraph,upstream_revision="fixture")
        self.assertEqual(calls[1],("propagate","MU","2026-10-15"))
        self.assertEqual(calls[0][1]["config"]["llm_provider"],"deepseek")
        self.assertEqual(x["reports"]["final_trade_decision"],"BUY")
        self.assertEqual(x["deepseek_role"],"sole trading decision-maker")

    def test_optional_input_only_handles_historical_data_as_unverified(self):
        x=bridge.make_advisory("NVDA","2026-06-01",
                               {"market_report":"Past data"},None)
        self.assertEqual(x["claim_status"],"unverified_external_research")
        self.assertTrue(any("as-of" in value for value in x["limitations"]))

if __name__=="__main__":
    unittest.main()

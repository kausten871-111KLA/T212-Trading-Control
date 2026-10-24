"""Alpaca gateway fixture integration, entirely offline and credential-free."""
import json
import unittest
from trading_brain_research_tool import Tools
from market_gateway_normalizer import normalise_snapshot, normalise_bars
from research_context import compile_context

ASOF="2026-10-21T14:40:00Z"
SNAPSHOT={
    "provider":"Alpaca", "feed":"iex","readOnly":True,
    "symbols":[{
        "symbol":"MYGN","price":5.54,"changePctVsPrevClose":31.4,
        "dayVolume":934853,"bid":4.77,"ask":6.37,"spreadPct":28.73,
        "quoteTimestamp":"2026-10-21T14:35:01Z",
        "tradeTimestamp":"2026-10-21T14:35:02Z",
    }]
}
BARS={
 "bars":{
  "MYGN":[
   {"t":"2026-10-21T13:30:00Z","o":5.0,"h":5.2,"l":4.9,"c":5.0,"v":100},
   {"t":"2026-10-21T13:35:00Z","o":5.0,"h":5.6,"l":5.0,"c":5.5,"v":200},
  ]
 },
 "next_page_token":None,
}


class NormalizerContract(unittest.IsolatedAsyncioTestCase):
    def test_normalises_actual_gateway_output(self):
        data=normalise_snapshot(SNAPSHOT,ticker="MYGN",as_of_utc=ASOF)
        r=data["observation"]
        self.assertEqual(data["data_source"],"Alpaca iex through existing WebUI gateway; research input")
        self.assertEqual(r["ticker"],"MYGN")
        self.assertEqual(r["quote_time_utc"],"2026-10-21T14:35:01Z")
        self.assertIsNone(r["rvol"])
        self.assertTrue(data["source_capture_time_supplied_by_caller"])

    def test_synthetic_capture_clearly_flagged(self):
        data=normalise_snapshot(SNAPSHOT,ticker="MYGN",as_of_utc=ASOF)
        result=compile_context(data,ticker="MYGN",as_of_utc=ASOF)
        self.assertTrue(result["source_evidence"]["observation_time_is_caller_supplied"])
        self.assertIn("provider_attested_snapshot_capture_time",result["missing_evidence"])
        self.assertFalse(result["source_evidence"]["source_raw_receipt_independently_verified"])

    async def test_direct_webui_tool_accepts_gateway_snapshot_and_bars(self):
        output=await Tools().trading_brain_research(
            ticker="MYGN",snapshot_json=json.dumps(SNAPSHOT),as_of_utc=ASOF,
            bars_json=json.dumps(BARS),average_daily_volume=150,
        )
        data=json.loads(output)
        self.assertEqual(data["ticker"],"MYGN")
        self.assertEqual(data["quote_economics_hypothetical"]["roundtrip_spread_cost"],"160.00")
        self.assertEqual(data["bar_features"]["relative_volume"],2)
        self.assertEqual(data["bar_features"]["bars"],2)
        self.assertEqual(data["history_as_of"],[])
        self.assertFalse(data["broker_order_instructions"])

    async def test_direct_default_no_bars_no_rvol(self):
        output=await Tools().trading_brain_research(
            ticker="MYGN",snapshot_json=json.dumps(SNAPSHOT),as_of_utc=ASOF)
        data=json.loads(output)
        self.assertIsNone(data["bar_features"]["relative_volume"])
        self.assertEqual(data["bar_features"]["bars"],0)

    def test_missing_provider_readonly_rejected(self):
        broken={**SNAPSHOT,"readOnly":False}
        with self.assertRaises(ValueError):
            normalise_snapshot(broken,ticker="MYGN",as_of_utc=ASOF)

    def test_wrong_feed_rejected(self):
        broken={**SNAPSHOT,"feed":"fake"}
        with self.assertRaises(ValueError):
            normalise_snapshot(broken,ticker="MYGN",as_of_utc=ASOF)

    def test_duplicate_symbol_rejected(self):
        broken={**SNAPSHOT,"symbols":SNAPSHOT["symbols"]*2}
        with self.assertRaises(ValueError):
            normalise_snapshot(broken,ticker="MYGN",as_of_utc=ASOF)

    def test_bar_timestamp_returned_without_invention(self):
        bars=normalise_bars(BARS,ticker="MYGN")
        self.assertEqual(bars[0]["timestamp_utc"],"2026-10-21T13:30:00Z")
        self.assertEqual(bars[1]["volume"],200)

    async def test_future_bar_rejected_by_context(self):
        wrong={"bars":{"MYGN":[{"t":"2026-10-23T14:00:00Z",
            "c":5,"v":100,"h":6,"l":4}]}}
        output=await Tools().trading_brain_research(
            ticker="MYGN",snapshot_json=json.dumps(SNAPSHOT),as_of_utc=ASOF,
            bars_json=json.dumps(wrong))
        self.assertFalse(json.loads(output)["ok"])

    def test_ticker_missing_in_bars_is_error(self):
        with self.assertRaises(ValueError):
            normalise_bars(BARS,ticker="NVDA")

    def test_fixture_input_kept_as_fixture(self):
        frozen={"dataset_id":"x","observation_timestamp_utc":ASOF,
                "candidates":[{"ticker":"MYGN"}]}
        self.assertEqual(normalise_snapshot(frozen,ticker="MYGN",as_of_utc=ASOF),frozen)

    def test_refuse_arbitrary_json_objects(self):
        with self.assertRaises(ValueError):
            normalise_snapshot({"foo":"bar"},ticker="MYGN",as_of_utc=ASOF)


if __name__=="__main__":
    unittest.main()

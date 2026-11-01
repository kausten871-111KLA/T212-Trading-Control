"""Offline regression tests for research_context.py, without broker or model access."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from finmem_research import connect, record_decision, add_outcome, add_reflection
from research_context import compile_context

ROOT=Path(__file__).resolve().parent.parent/"benchmark"
FIXTURE=json.loads((ROOT/"alpaca_eod_20261020_20.json").read_text())
REAL=json.loads((ROOT/"results/tradingagents_native_real_3symbols.json").read_text())
DECISIONS={x["ticker"]:x for x in REAL["decisions"]}
CUTOFF="2026-10-21T14:00:00Z"


def context(ticker="MYGN",**kwargs):
    return compile_context(FIXTURE,ticker=ticker,as_of_utc=CUTOFF,**kwargs)


class ContextTests(unittest.TestCase):
    def test_default_packet_research_only_and_not_exec(self):
        result=context()
        self.assertTrue(result["research_only"])
        self.assertFalse(result["broker_order_instructions"])
        self.assertFalse(result["decision_action_changed"])
        self.assertFalse(result["source_evidence"]["source_raw_receipt_independently_verified"])

    def test_mygn_quote_cost_is_evidence_only(self):
        result=context(quantity=100,decision=DECISIONS["MYGN"])
        self.assertEqual(result["quote_economics_hypothetical"]["roundtrip_spread_cost"],"160.00")
        self.assertEqual(result["decision_quality_advisory"]["action"],"BUY")
        self.assertIn("reported_spread_pct_28.73",result["decision_quality_advisory"]["flags"])
        self.assertIn("timestamped_bid_ask_quote",result["missing_evidence"])
        self.assertEqual(result["source_evidence"]["observation"]["catalyst"],None)

    def test_prso_not_excluded_solely_because_penny(self):
        result=context("PRSO",decision=DECISIONS["PRSO"])
        self.assertIn("No trade caps",result["limitations"][-1])
        self.assertEqual(result["decision_quality_advisory"]["action"],"HOLD")

    def test_context_all_twenty_without_price(self):
        contexts=[context(row["ticker"]) for row in FIXTURE["candidates"]]
        self.assertEqual(len(contexts),20)
        self.assertEqual(sum(row["quote_economics_hypothetical"]["bid"] is not None
                             for row in contexts),7)

    def test_repeatable_digest(self):
        self.assertEqual(context()["evidence_sha256"],context()["evidence_sha256"])

    def test_tampered_price_changes_digest(self):
        modified=copy.deepcopy(FIXTURE)
        modified["candidates"][1]["price"]=100
        self.assertNotEqual(compile_context(modified,ticker="MYGN",as_of_utc=CUTOFF)["evidence_sha256"],
                            context()["evidence_sha256"])

    def test_future_snapshot_rejected(self):
        with self.assertRaises(ValueError):
            compile_context(FIXTURE,ticker="MYGN",as_of_utc="2026-10-20T20:30:00Z")

    def test_unknown_ticker_rejected(self):
        with self.assertRaises(ValueError):
            context("MISSING")

    def test_duplicate_snapshot_symbol_rejected(self):
        modified=copy.deepcopy(FIXTURE)
        modified["candidates"].append(copy.deepcopy(modified["candidates"][0]))
        with self.assertRaises(ValueError):
            compile_context(modified,ticker="BRZE",as_of_utc=CUTOFF)

    def test_future_quote_timestamp_rejected(self):
        modified=copy.deepcopy(FIXTURE)
        modified["candidates"][1]["quote_time_utc"]="2026-10-22T18:00:00Z"
        with self.assertRaises(ValueError):
            compile_context(modified,ticker="MYGN",as_of_utc=CUTOFF)

    def test_unknown_future_bar_rejected(self):
        with self.assertRaises(ValueError):
            context(bars=[{"timestamp_utc":"2026-10-22T18:00:00Z",
                           "close":10,"volume":20}])

    def test_bars_produce_features_and_conditional_rvol(self):
        bars=[
            {"timestamp_utc":"2026-10-21T13:30:00Z","close":5.0,"volume":100,
             "high":5.2,"low":4.9},
            {"timestamp_utc":"2026-10-21T13:35:00Z","close":5.5,"volume":200,
             "high":5.6,"low":5.2},
        ]
        v=context(bars=bars,average_daily_volume=150)
        self.assertEqual(v["bar_features"]["bars"],2)
        self.assertAlmostEqual(v["bar_features"]["momentum_return_pct"],10.0)
        self.assertEqual(v["bar_features"]["relative_volume"],2)

    def test_no_bars_no_fabricated_features(self):
        v=context()
        self.assertIsNone(v["bar_features"]["relative_volume"])
        self.assertIsNone(v["bar_features"]["volume_weighted_price"])

    def test_limit_bars(self):
        with self.assertRaises(ValueError):
            context(bars=[{}]*801)

    def test_quote_incomplete_rejected(self):
        modified=copy.deepcopy(FIXTURE)
        modified["candidates"][1]["ask"]=None
        with self.assertRaises(ValueError):
            compile_context(modified,ticker="MYGN",as_of_utc=CUTOFF)

    def test_decision_ticker_mismatch_rejected(self):
        with self.assertRaises(ValueError):
            context("BRZE",decision=DECISIONS["MYGN"])

    def test_only_prior_memories_are_returned(self):
        with tempfile.TemporaryDirectory() as td:
            db=connect(Path(td)/"context_test.sqlite3")
            try:
                evidence=REAL["evidence_sha256"]
                record_decision(db,decision_id="d1",ticker="MYGN",phase="research",
                                observed_at_utc="2026-10-21T13:00:00Z",
                                thesis="Prior recorded decision",evidence_sha256=evidence)
                add_outcome(db,decision_id="d1",
                            known_at_utc="2026-10-22T16:00:00Z",
                            label="PRICE_UP",observation="Later verified price")
                r=context(memory_db=db)
                self.assertEqual(len(r["history_as_of"]),1)
                self.assertIsNone(r["history_as_of"][0]["outcome"])
                self.assertEqual(r["history_as_of"][0]["thesis"],"Prior recorded decision")
            finally:
                db.close()

    def test_prior_memory_outcome_visible_when_known(self):
        with tempfile.TemporaryDirectory() as td:
            db=connect(Path(td)/"context_test.sqlite3")
            try:
                record_decision(db,decision_id="d1",ticker="MYGN",
                                phase="research",observed_at_utc="2026-10-20T21:40:00Z",
                                thesis="No catalyst proof",evidence_sha256=REAL["evidence_sha256"])
                add_outcome(db,decision_id="d1",known_at_utc="2026-10-21T11:00:00Z",
                            label="NO_TRADE",observation="Verified broker returned empty orders")
                result=context(memory_db=db)
                self.assertEqual(result["history_as_of"][0]["outcome"]["label"],"NO_TRADE")
                self.assertEqual(len(result["history_as_of"]),1)
            finally:
                db.close()

    def test_absent_memory_is_empty_not_simulated(self):
        self.assertEqual(context()["history_as_of"],[])

    def test_hypothesis_unverified(self):
        result=context("BRZE")
        self.assertIn("Takeover",result["catalyst_hypothesis_unverified"])
        self.assertIn("independent_primary_catalyst_source",result["missing_evidence"])

    def test_leveraged_symbol_not_categorically_rejected(self):
        result=context("SOXL")
        self.assertTrue(result["research_only"])
        self.assertNotIn("automatic_reject", result)
        self.assertFalse("excluded" in result)

    def test_no_import_of_broker_client(self):
        source=(Path(__file__).parent/"research_context.py").read_text()
        for disallowed in ("trading212_demo_gateway","place_market_order","httpx","requests"):
            self.assertNotIn(disallowed,source)

if __name__=="__main__":
    unittest.main()

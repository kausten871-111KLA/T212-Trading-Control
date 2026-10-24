"""Offline tests for Trading Brain candidate capabilities; never call providers."""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from pathlib import Path
import hashlib
import json
import tempfile
import unittest

from quote_economics import quote_economics, quote_audit
from momentum_features import analyse_bars
from finmem_research import connect, record_decision, add_outcome, add_reflection, retrieve
from evidence_review import assess_decision, review_fixture

FOLDER=Path(__file__).resolve().parent
BENCHMARK=FOLDER.parent/"benchmark"
FIXTURE=json.loads((BENCHMARK/"alpaca_eod_20261020_20.json").read_text())
TRIAL=json.loads((BENCHMARK/"results/tradingagents_native_real_3symbols.json").read_text())
ROWS={x["ticker"]:x for x in FIXTURE["candidates"]}
DECISIONS={x["ticker"]:x for x in TRIAL["decisions"]}
SHA=TRIAL["evidence_sha256"]


class QuoteEconomicsTests(unittest.TestCase):
    def test_mygn_roundtrip_100_shares(self):
        v=quote_economics(ROWS["MYGN"],quantity=100)
        self.assertEqual(v["quote_status"],"OBSERVED_NOT_EXECUTABLE")
        self.assertEqual(v["roundtrip_spread_cost"],"160.00")
        self.assertAlmostEqual(v["spread_pct_mid"],28.725314,places=4)

    def test_prso_sub_dollar_not_preemptively_rejected(self):
        v=quote_economics(ROWS["PRSO"],quantity=100)
        self.assertEqual(v["roundtrip_spread_cost"],"16.00")
        self.assertTrue(v["observation_only"])

    def test_broker_absent_quote_returns_null(self):
        v=quote_economics(ROWS["NVDA"])
        self.assertIsNone(v["roundtrip_total_cost"])
        self.assertEqual(v["quote_status"],"MISSING_QUOTE")

    def test_quotes_bulk_covers_20(self):
        items=quote_audit(FIXTURE["candidates"])
        self.assertEqual(len(items),20)
        self.assertEqual(sum(x["roundtrip_total_cost"] is not None for x in items),7)

    def test_fee_and_slippage_explicit_scenario(self):
        row={"ticker":"X","bid":9,"ask":10}
        v=quote_economics(row,quantity=2,fee_per_side=1,slippage_each_side=.5)
        self.assertEqual(v["roundtrip_spread_cost"],"2")
        self.assertEqual(v["roundtrip_total_cost"],"5.0")

    def test_negative_fee_rejected(self):
        with self.assertRaises(ValueError):
            quote_economics(ROWS["MYGN"],fee_per_side=-1)

    def test_inverted_quote_rejected(self):
        with self.assertRaises(ValueError):
            quote_economics({"ticker":"X","bid":11,"ask":10})

    def test_half_quote_rejected(self):
        with self.assertRaises(ValueError):
            quote_economics({"ticker":"X","bid":11,"ask":None})

    def test_quote_timestamp_not_assumed(self):
        self.assertIsNone(quote_economics(ROWS["BRZE"])["quote_time_utc"])
        self.assertFalse(quote_economics(ROWS["BRZE"])["freshness_verified"])


class MomentumFeatureTests(unittest.TestCase):
    ASOF="2026-10-20T21:40:00Z"
    BARS=[
        {"timestamp_utc":"2026-10-20T14:00:00Z","close":10,"volume":100,"high":11,"low":9},
        {"timestamp_utc":"2026-10-20T16:00:00Z","close":11,"volume":200,"high":12,"low":10},
    ]

    def test_empty_fixture_returns_missing(self):
        v=analyse_bars([],as_of_utc=self.ASOF)
        self.assertIsNone(v["relative_volume"])
        self.assertIsNone(v["momentum_return_pct"])
        self.assertIsNone(v["volume_weighted_price"])

    def test_two_bars_return_ten_percent(self):
        v=analyse_bars(self.BARS,as_of_utc=self.ASOF)
        self.assertAlmostEqual(v["momentum_return_pct"],10)
        self.assertAlmostEqual(v["volume_weighted_price"],(10*100+11*200)/300)

    def test_rvol_requires_user_supplied_reference(self):
        v=analyse_bars(self.BARS,as_of_utc=self.ASOF)
        self.assertIsNone(v["relative_volume"])
        self.assertIn("Historical comparable-volume baseline for RVOL",v["missing_inputs"])

    def test_rvol_with_reference(self):
        v=analyse_bars(self.BARS,as_of_utc=self.ASOF,average_daily_volume=150)
        self.assertEqual(v["relative_volume"],2)

    def test_future_bar_fails(self):
        future=self.BARS+[{"timestamp_utc":"2026-10-21T12:00:00Z","close":12,"volume":400}]
        with self.assertRaises(ValueError):
            analyse_bars(future,as_of_utc=self.ASOF)

    def test_unsorted_bars_fail(self):
        with self.assertRaises(ValueError):
            analyse_bars(self.BARS[::-1],as_of_utc=self.ASOF)

    def test_zero_volume_is_not_vwap(self):
        bars=[{**v,"volume":0} for v in self.BARS]
        v=analyse_bars(bars,as_of_utc=self.ASOF)
        self.assertIsNone(v["volume_weighted_price"])

    def test_naive_cutoff_rejected(self):
        with self.assertRaises(ValueError):
            analyse_bars(self.BARS,as_of_utc="2026-10-20T21:40:00")

    def test_invalid_high_low_rejected(self):
        bars=[{**self.BARS[0],"high":9},self.BARS[1]]
        with self.assertRaises(ValueError):
            analyse_bars(bars,as_of_utc=self.ASOF)


class FinMemTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.db=connect(Path(self.t.name)/"research-only.sqlite3")
        self.addCleanup(self.db.close)
        record_decision(self.db,decision_id="d1",ticker="MYGN",
            observed_at_utc="2026-10-20T20:00:00Z",phase="research",
            thesis="No verified catalyst",evidence_sha256=SHA)

    def test_before_decision_is_invisible(self):
        self.assertEqual(retrieve(self.db,as_of_utc="2026-10-20T19:59:59Z"),[])

    def test_decision_without_outcome(self):
        row=retrieve(self.db,as_of_utc="2026-10-20T21:00:00Z")[0]
        self.assertEqual(row["memory_tier"],"short")
        self.assertIsNone(row["outcome"])

    def test_outcome_not_available_before_publication(self):
        add_outcome(self.db,decision_id="d1",known_at_utc="2026-10-21T10:00:00Z",
            label="UP",observation="Later price move")
        self.assertIsNone(retrieve(self.db,as_of_utc="2026-10-20T21:40:00Z")[0]["outcome"])
        self.assertEqual(retrieve(self.db,as_of_utc="2026-10-21T10:01:00Z")[0]["outcome"]["label"],"UP")

    def test_immutable_decision_rejected(self):
        with self.assertRaises(Exception):
            record_decision(self.db,decision_id="d1",ticker="MYGN",
                observed_at_utc="2026-10-21T10:00:00Z",phase="research",
                thesis="edited hindsight",evidence_sha256=SHA)

    def test_reflection_visibility(self):
        add_reflection(self.db,reflection_id="r1",decision_id="d1",
            known_at_utc="2026-10-21T12:00:00Z",lesson="Spread mattered")
        self.assertEqual(retrieve(self.db,as_of_utc="2026-10-21T11:00:00Z")[0]["reflections"],[])
        self.assertEqual(len(retrieve(self.db,as_of_utc="2026-10-21T12:00:01Z")[0]["reflections"]),1)

    def test_memory_tier_short_medium_long(self):
        self.assertEqual(retrieve(self.db,as_of_utc="2026-10-20T21:00:00Z")[0]["memory_tier"],"short")
        self.assertEqual(retrieve(self.db,as_of_utc="2026-10-22T21:00:00Z")[0]["memory_tier"],"medium")
        self.assertEqual(retrieve(self.db,as_of_utc="2026-11-06T21:00:00Z")[0]["memory_tier"],"long")

    def test_outcome_before_decision_rejected(self):
        with self.assertRaises(ValueError):
            add_outcome(self.db,decision_id="d1",known_at_utc="2026-10-19T21:00:00Z",
                        label="UP",observation="invalid")

    def test_filtered_by_ticker_and_phase(self):
        self.assertEqual(len(retrieve(self.db,as_of_utc="2026-10-20T21:00:00Z",ticker="NVDA")),0)
        self.assertEqual(len(retrieve(self.db,as_of_utc="2026-10-20T21:00:00Z",ticker="MYGN",phase="research")),1)

    def test_no_future_reflection(self):
        with self.assertRaises(ValueError):
            add_reflection(self.db,reflection_id="r1",decision_id="d1",
                        known_at_utc="2026-10-19T21:00:00Z",lesson="future leak")


class EvidenceReviewTests(unittest.TestCase):
    def test_existing_actual_mygn_buy_preserved(self):
        original=deepcopy(DECISIONS["MYGN"])
        review=assess_decision(original,ROWS["MYGN"])
        self.assertEqual(review["action"],"BUY")
        self.assertFalse(review["action_changed"])
        self.assertEqual(original,DECISIONS["MYGN"])

    def test_prso_quote_spread_flag_and_text(self):
        v=assess_decision(DECISIONS["PRSO"],ROWS["PRSO"])
        self.assertIn("reported_spread_pct_27.09",v["flags"])

    def test_mygn_quote_spread_flag(self):
        v=assess_decision(DECISIONS["MYGN"],ROWS["MYGN"])
        self.assertIn("reported_spread_pct_28.73",v["flags"])
        self.assertIn("missing_rvol",v["flags"])

    def test_only_three_native_outputs(self):
        rows=review_fixture(FIXTURE,TRIAL["decisions"])
        self.assertEqual(len(rows),3)
        self.assertEqual([x["ticker"] for x in rows],["BRZE","MYGN","PRSO"])

    def test_duplicate_rejected(self):
        with self.assertRaises(ValueError):
            review_fixture(FIXTURE,[DECISIONS["BRZE"],DECISIONS["BRZE"]])

    def test_symbol_mismatch_rejected(self):
        with self.assertRaises(ValueError):
            assess_decision(DECISIONS["MYGN"],ROWS["BRZE"])

    def test_catalysts_not_treated_as_verified(self):
        rows=review_fixture(FIXTURE,TRIAL["decisions"])
        self.assertTrue(all(not x["catalyst_verified"] for x in rows))

    def test_no_broker_in_modules(self):
        for module in ["quote_economics.py","momentum_features.py",
                       "finmem_research.py","evidence_review.py"]:
            content=(FOLDER/module).read_text()
            self.assertNotIn("place_market_order",content)
            self.assertNotIn("import requests",content)
            self.assertNotIn("import openai",content)


if __name__=="__main__":
    unittest.main()

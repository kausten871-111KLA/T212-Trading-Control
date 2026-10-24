"""End-to-end offline three-symbol evidence and FinMem replay regression."""
import json
import tempfile
import unittest
from pathlib import Path

from offline_replay import replay
from finmem_research import connect, retrieve

ROOT=Path(__file__).parent.parent/"benchmark"
FIXTURE=ROOT/"alpaca_eod_20261020_20.json"
BASELINE=ROOT/"results/deepseek_baseline_validated_20261020.json"
NATIVE=ROOT/"results/tradingagents_native_real_3symbols.json"

class OfflineReplayTest(unittest.TestCase):
    def run_report(self,asof="2026-10-21T12:00:00Z"):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path=Path(temp.name)/"research.sqlite3"
        return replay(FIXTURE,BASELINE,NATIVE,sqlite_path=path,as_of_utc=asof),path

    def test_three_real_symbols_and_actions(self):
        r,_=self.run_report()
        self.assertEqual([(x["ticker"],x["challenger_action"]) for x in r["rows"]],
                         [("BRZE","HOLD"),("MYGN","BUY"),("PRSO","HOLD")])
        self.assertTrue(all(x["baseline_action"]=="WAIT" for x in r["rows"]))

    def test_no_orders_or_paid_calls_in_replay(self):
        r,_=self.run_report()
        self.assertEqual(r["model_calls_this_replay"],0)
        self.assertEqual(r["broker_orders_this_replay"],0)
        self.assertFalse(r["trades_executed_from_research"])

    def test_mygn_spread_scenario_is_not_a_fill(self):
        r,_=self.run_report()
        row=next(x for x in r["rows"] if x["ticker"]=="MYGN")
        econ=row["quote_costs_scenario_100_shares"]
        self.assertEqual(econ["roundtrip_spread_cost"],"160.00")
        self.assertEqual(econ["quote_status"],"OBSERVED_NOT_EXECUTABLE")

    def test_no_momentum_in_eod_fixture(self):
        r,_=self.run_report()
        self.assertTrue(all(x["momentum_from_available_bars"]["momentum_return_pct"] is None
                            for x in r["rows"]))
        self.assertTrue(all(x["momentum_from_available_bars"]["relative_volume"] is None
                            for x in r["rows"]))

    def test_memory_contains_no_fabricated_outcomes(self):
        r,_=self.run_report()
        self.assertEqual(r["memory_decisions_visible_as_of"],3)
        self.assertEqual(r["memory_outcomes_visible_as_of"],0)

    def test_point_in_time_before_trial_has_no_memory(self):
        r,_=self.run_report(asof="2026-10-20T21:40:00Z")
        self.assertEqual(r["memory_decisions_visible_as_of"],0)

    def test_wrong_baseline_hash_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            original=json.loads(BASELINE.read_text())
            original["evidence_sha256"]="wrong"
            altered=Path(temp)/"bad.json"
            altered.write_text(json.dumps(original))
            with self.assertRaises(ValueError):
                replay(FIXTURE,altered,NATIVE,sqlite_path=Path(temp)/"db.sqlite",
                       as_of_utc="2026-10-21T12:00:00Z")

    def test_mock_trial_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            original=json.loads(NATIVE.read_text())
            original["mocked"]=True
            altered=Path(temp)/"bad.json"
            altered.write_text(json.dumps(original))
            with self.assertRaises(ValueError):
                replay(FIXTURE,BASELINE,altered,sqlite_path=Path(temp)/"db.sqlite",
                       as_of_utc="2026-10-21T12:00:00Z")

if __name__=="__main__":
    unittest.main()

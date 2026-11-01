"""Offline tests for normalising the user-submitted DeepSeek baseline."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from trading_brain_benchmark import load_fixture, observation_only, validate_decisions
from normalize_baseline import normalize

ROOT=Path(__file__).parent
FIXTURE=ROOT/"alpaca_eod_20261020_20.json"
RAW=ROOT/"results/deepseek_baseline_original_20261020.json"

class BaselineTests(unittest.TestCase):
    def test_preserves_20_actions_and_all_free_text(self):
        norm,report=normalize(RAW,FIXTURE)
        raw=json.loads(RAW.read_text())
        self.assertEqual(len(norm["decisions"]),20)
        for a,b in zip(raw["decisions"],norm["decisions"]):
            for field in ("ticker","action","thesis","bull_case","bear_case"):
                self.assertEqual(a[field],b[field])
        self.assertEqual(report["actions"],{"WAIT":6,"RESEARCH":14})
        self.assertEqual(report["unsupported_reference_occurrences"],5)

    def test_strict_schema_passes_after_normalization(self):
        norm,_=normalize(RAW,FIXTURE)
        with tempfile.TemporaryDirectory() as td:
            output=Path(td)/"normalized.json"
            output.write_text(json.dumps(norm))
            result=validate_decisions(output,observation_only(load_fixture(FIXTURE)))
        self.assertEqual(len(result["decisions"]),20)

    def test_external_references_recorded_not_used_as_evidence(self):
        norm,report=normalize(RAW,FIXTURE)
        issues={e["ticker"]:e["unsupported_references"] for e in report["unsupported_ticker_references"]}
        self.assertEqual(issues,{
            "IREN":["CIFR"],"BITO":["BTC"],
            "SOXL":["SOXX"],"SOXS":["SOXX"],"MSTZ":["MSTR"]
        })
        known={x["ticker"] for x in norm["decisions"]}
        self.assertTrue(all(set(x["evidence_tickers"]) <= known for x in norm["decisions"]))
        self.assertEqual(next(x for x in norm["decisions"] if x["ticker"]=="IREN")["evidence_tickers"],["CRWV"])
        self.assertTrue(all(
            "not in the frozen 20-symbol evidence" in note
            for row in norm["decisions"] for note in row["missing_evidence"]
            if note.startswith("External symbol ")
        ))

    def test_mismatched_evidence_hash_rejected(self):
        original=json.loads(RAW.read_text())
        original["evidence_sha256"]="invalid"
        with tempfile.TemporaryDirectory() as td:
            corrupted=Path(td)/"input.json"
            corrupted.write_text(json.dumps(original))
            with self.assertRaises(AssertionError):
                normalize(corrupted,FIXTURE)

if __name__=="__main__":
    unittest.main()

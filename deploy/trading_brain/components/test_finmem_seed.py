"""Regression for source-backed FinMem research bootstrap."""
from __future__ import annotations
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import seed_finmem_from_research as module
from finmem_research import connect, retrieve, add_outcome

class SeedTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path=Path(self.folder.name)/"independent-finmem.sqlite3"

    def test_three_real_decisions_with_no_outcomes(self):
        result=module.seed(self.path)
        self.assertEqual(result["created"],3)
        db=connect(self.path)
        self.addCleanup(db.close)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM research_decision").fetchone()[0],3)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM research_outcome").fetchone()[0],0)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM research_reflection").fetchone()[0],0)

    def test_idempotent_no_duplicate(self):
        module.seed(self.path)
        result=module.seed(self.path)
        self.assertEqual(result["created"],0)
        self.assertEqual(result["total_seeded"],3)

    def test_real_model_actions_labeled_as_research(self):
        module.seed(self.path)
        db=connect(self.path)
        self.addCleanup(db.close)
        for name, action in (("BRZE","HOLD"),("MYGN","BUY"),("PRSO","HOLD")):
            records=retrieve(db,as_of_utc="2026-10-22T08:00:00Z",ticker=name)
            self.assertEqual(len(records),1)
            self.assertIn("PROPOSED RESEARCH ACTION "+action,records[0]["thesis"])
            self.assertIn("NOT AN ORDER",records[0]["thesis"])
            self.assertIsNone(records[0]["outcome"])

    def test_refuse_hindsight_before_assessment(self):
        module.seed(self.path)
        db=connect(self.path)
        self.addCleanup(db.close)
        self.assertEqual(retrieve(db,as_of_utc="2026-10-20T22:30:00Z"),[])

    def test_exact_evidence_fingerprint(self):
        result=module.seed(self.path)
        self.assertEqual(result["sha256_evidence"],
                         "cbf27160ec376c2355729d1f1eeb05e6a30082128eff2c46b99fa617f32c49d1")

    def test_user_baseline_without_time_not_imported(self):
        result=module.seed(self.path)
        self.assertFalse(result["baseline_without_assessment_timestamp_imported"])
        self.assertEqual(result["total_seeded"],3)

    def test_reseed_preserves_known_outcome(self):
        module.seed(self.path)
        db=connect(self.path)
        add_outcome(db,decision_id="native-nine-call-20261020-MYGN",
                    known_at_utc="2026-10-22T07:00:00Z",
                    label="research_observed",observation="Separately verified later information")
        db.close()
        result=module.seed(self.path)
        self.assertEqual(result["created"],0)
        db=connect(self.path)
        self.addCleanup(db.close)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM research_outcome").fetchone()[0],1)

    def test_existing_mutated_thesis_rejected(self):
        module.seed(self.path)
        c=sqlite3.connect(self.path)
        c.execute("UPDATE research_decision SET thesis='fabricated' WHERE ticker='MYGN'")
        c.commit();c.close()
        with self.assertRaises(ValueError):
            module.seed(self.path)

    def test_invalid_trial_source_fingerprint_rejected(self):
        records=module.expected_seed_records()
        self.assertEqual(len(records),3)
        from copy import deepcopy
        import json
        altered=json.loads(module.TRIAL.read_text())
        altered["evidence_sha256"]="0"*64
        path=Path(self.folder.name)/"tampered.json"
        path.write_text(json.dumps(altered))
        with patch.object(module,"TRIAL",path):
            with self.assertRaises(ValueError):
                module.expected_seed_records()

    def test_cannot_convert_model_decisions_to_fills(self):
        module.seed(self.path)
        db=connect(self.path)
        self.addCleanup(db.close)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM research_outcome").fetchone()[0],0)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM research_decision WHERE phase='broker_execution'").fetchone()[0],0)

if __name__=="__main__":
    unittest.main()

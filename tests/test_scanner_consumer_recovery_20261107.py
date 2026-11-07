"""Synthetic crash/restart and missing-stage acceptance; no model, provider or broker I/O."""
from __future__ import annotations
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from runtime.deepseek.scanner_candidate_consumer import ScannerCandidateConsumer, ConsumerError

T0="2026-11-07T05:00:00Z"
T1="2026-11-07T05:00:05Z"
T2="2026-11-07T05:00:10Z"
T3="2026-11-07T05:00:45Z"
T4="2026-11-07T05:00:50Z"

def page():
    return {"ok":True,"command":"scanner_candidates","cursor_requested":-1,
            "records":[{"id":201,"symbol":"SYNTHETIC"},{"id":202,"symbol":"SYNTHETIC"}],
            "next_cursor":202,"max_id_at_read":202}

def lookup(batch):
    def resolve(*,stage,receipt_id):
        return {"source":"authenticated_webui_host_terminal","stage":stage,
                "receipt_id":receipt_id,"batch_id":batch,
                "candidate_ids":[201,202],"terminal":"completed"}
    return resolve

class RestartAndMissingStageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory(prefix="p1_recovery_synthetic_")
        self.path=Path(self.tmp.name)/"ledger.sqlite"
        self.c=ScannerCandidateConsumer(self.path)
        self.batch=self.c.stage_page(page(),requested_cursor=-1,now_utc=T0)
    def tearDown(self):
        self.c.close()
        self.tmp.cleanup()
    def restart(self):
        self.c.close()
        self.c=ScannerCandidateConsumer(self.path)
    def claim(self,who="A",when=T1,budget=3):
        return self.c.claim_for_model(worker_id=who,max_calls_per_utc_day=budget,
                                      lease_seconds=30,now_utc=when)
    def stage(self,stage,receipt,who="A",when=T2):
        self.c.receipt_lookup=lookup(self.batch)
        return self.c.record_verified_stage(batch_id=self.batch,worker_id=who,
            stage=stage,receipt_id=receipt,candidate_ids=[201,202],now_utc=when)
    def ack(self,who="A",when=T2,inv="i1",dec="d1"):
        return self.c.acknowledge(batch_id=self.batch,worker_id=who,
            investigator_receipt_id=inv,decision_receipt_id=dec,
            candidate_ids=[201,202],investigator_ack=True,decision_ack=True,
            now_utc=when)
    def test_crash_after_staging_before_claim_stays_pending(self):
        self.restart()
        self.assertEqual(-1,self.c.cursor())
        self.assertEqual("pending",self.c.pending_batch(now_utc=T1)["state"])
        self.assertIsNone(self.claim(budget=0))
        self.assertEqual(-1,self.c.cursor())
    def test_crash_after_claim_reclaims_only_after_expiry(self):
        self.claim()
        self.restart()
        self.assertIsNone(self.claim("B",T2))
        replacement=self.claim("B",T3)
        self.assertEqual("B",replacement["lease_owner"])
        self.assertEqual(2,replacement["attempts"])
        self.assertEqual(-1,self.c.cursor())
    def test_crash_after_investigator_without_decision_rejects_ack(self):
        self.claim()
        self.stage("INVESTIGATOR","i1")
        self.restart()
        with self.assertRaisesRegex(ConsumerError,"two independently verified"):
            self.ack()
        self.assertEqual(-1,self.c.cursor())
        self.assertEqual({"INVESTIGATOR":1},self.c.status()["stage_receipt_counts"])
    def test_crash_after_both_receipts_does_not_auto_ack(self):
        self.claim()
        self.stage("INVESTIGATOR","i1")
        self.stage("DECISION","d1")
        self.restart()
        self.assertEqual(-1,self.c.cursor())
        self.assertEqual({"in_flight":1},self.c.status()["batch_counts"])
        self.assertEqual(202,self.ack())
    def test_unverified_decision_does_not_unlock_cursor(self):
        self.claim()
        self.stage("INVESTIGATOR","i1")
        self.c.receipt_lookup=None
        with self.assertRaisesRegex(ConsumerError,"lookup not installed"):
            self.c.record_verified_stage(batch_id=self.batch,worker_id="A",
                stage="DECISION",receipt_id="d1",candidate_ids=[201,202],now_utc=T2)
        with self.assertRaisesRegex(ConsumerError,"two independently verified"):
            self.ack()
        self.assertEqual(-1,self.c.cursor())

if __name__=="__main__":
    unittest.main()

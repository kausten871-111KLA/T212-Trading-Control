"""Concurrency and replay-integrity tests; temporary SQLite only, no provider or model I/O."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from threading import Barrier
import sqlite3
import tempfile
import unittest

from runtime.deepseek.scanner_candidate_consumer import ScannerCandidateConsumer,ConsumerError

T0="2026-11-07T00:40:00Z"
T1="2026-11-07T00:40:05Z"
T2="2026-11-07T00:40:10Z"
T3="2026-11-07T00:40:45Z"

def page(before=-1,ids=(101,102),symbols=None,maximum=102):
    symbols=symbols or ["AAA"]*len(ids)
    return {"ok":True,"command":"scanner_candidates","cursor_requested":before,
            "records":[{"id":i,"symbol":symbol,"signals":["synthetic"]} for i,symbol in zip(ids,symbols)],
            "next_cursor":ids[-1],"max_id_at_read":maximum}

class ConcurrencySafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix="p1_isolated_multiworker_")
        self.dbfile=Path(self.tmp.name)/"ledger.sqlite3"
        c=ScannerCandidateConsumer(self.dbfile)
        c.close()
    def tearDown(self):
        self.tmp.cleanup()

    def concurrent(self,fun):
        barrier=Barrier(2)
        def go(i):
            c=ScannerCandidateConsumer(self.dbfile)
            try:
                barrier.wait(timeout=4)
                return fun(c,i)
            finally:
                c.close()
        with ThreadPoolExecutor(max_workers=2) as executor:
            return list(executor.map(go,(0,1)))

    def test_simultaneous_identical_page_idempotent(self):
        out=self.concurrent(lambda c,i:c.stage_page(page(),requested_cursor=-1,now_utc=T0))
        self.assertEqual(out[0],out[1])
        with closing(ScannerCandidateConsumer(self.dbfile)) as c:
            self.assertEqual(1,c.db.execute("SELECT count(*) FROM consumer_batch").fetchone()[0])
            self.assertEqual(-1,c.cursor())

    def test_concurrent_divergent_pages_do_not_replace_pending(self):
        def task(c,i):
            try:
                return ("ok",c.stage_page(page(ids=(101+i*10,102+i*10),maximum=112),requested_cursor=-1,now_utc=T0))
            except ConsumerError as e:
                return ("blocked",str(e))
        outcomes=self.concurrent(task)
        self.assertEqual(["blocked","ok"],sorted(x[0] for x in outcomes))
        with closing(ScannerCandidateConsumer(self.dbfile)) as c:
            self.assertEqual(1,c.db.execute("SELECT count(*) FROM consumer_batch").fetchone()[0])
            self.assertEqual(-1,c.cursor())

    def test_two_workers_cannot_claim_same_batch(self):
        with closing(ScannerCandidateConsumer(self.dbfile)) as c:
            c.stage_page(page(),requested_cursor=-1,now_utc=T0)
        results=self.concurrent(lambda c,i:c.claim_for_model(
            worker_id=f"worker-{i}", max_calls_per_utc_day=2,now_utc=T1,lease_seconds=30))
        self.assertEqual(1,sum(x is not None for x in results))
        with closing(ScannerCandidateConsumer(self.dbfile)) as c:
            self.assertEqual(-1,c.cursor())
            self.assertEqual(1,c.db.execute("SELECT calls_reserved FROM model_call_budget").fetchone()[0])
            self.assertEqual(1,c.db.execute("SELECT attempts FROM consumer_batch").fetchone()[0])

    def test_replayed_ids_must_preserve_original_evidence(self):
        with closing(ScannerCandidateConsumer(self.dbfile)) as c:
            first=c.stage_page(page(),requested_cursor=-1,now_utc=T0)
            self.assertEqual(first,c.stage_page(page(maximum=120),requested_cursor=-1,now_utc=T1))
            altered=page(maximum=120,symbols=["AAA","CHANGED"])
            with self.assertRaisesRegex(ConsumerError,"evidence changed"):
                c.stage_page(altered,requested_cursor=-1,now_utc=T2)
            self.assertEqual(-1,c.cursor())
            self.assertEqual(1,c.db.execute("SELECT count(*) FROM consumer_batch").fetchone()[0])
            saved=c.db.execute("SELECT payload_json FROM consumer_batch").fetchone()[0]
            self.assertNotIn("CHANGED",saved)

    def test_expired_lease_fences_original_worker(self):
        with closing(ScannerCandidateConsumer(self.dbfile)) as c:
            batch=c.stage_page(page(),requested_cursor=-1,now_utc=T0)
            c.claim_for_model(worker_id="original",max_calls_per_utc_day=2,
                              now_utc=T1,lease_seconds=30)
            renewed=c.claim_for_model(worker_id="replacement",max_calls_per_utc_day=2,
                                      now_utc=T3,lease_seconds=30)
            self.assertEqual("replacement",renewed["lease_owner"])
            c.receipt_lookup=lambda **kwargs:{"source":"authenticated_webui_host_terminal",
                 "stage":kwargs["stage"],"receipt_id":kwargs["receipt_id"],"batch_id":batch,
                 "candidate_ids":[101,102],"terminal":"completed"}
            with self.assertRaisesRegex(ConsumerError,"active owned batch"):
                c.record_verified_stage(batch_id=batch,worker_id="original",
                    stage="INVESTIGATOR",receipt_id="synthetic-inv-1",
                    candidate_ids=[101,102],now_utc=T3)
            self.assertEqual(0,c.db.execute("SELECT count(*) FROM consumer_stage_receipt").fetchone()[0])
            self.assertEqual(-1,c.cursor())

if __name__ == "__main__":
    unittest.main()

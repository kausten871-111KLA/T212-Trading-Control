"""Synthetic, no-network scanner consumer tests. No host/model/broker access."""
from __future__ import annotations
import tempfile
from pathlib import Path
import unittest

from runtime.deepseek.scanner_candidate_consumer import ScannerCandidateConsumer, ConsumerError

T0="2026-11-06T10:00:00Z"
T1="2026-11-06T10:00:05Z"
T2="2026-11-06T10:00:10Z"
T3="2026-11-06T10:00:20Z"
T31="2026-11-06T10:00:31Z"
T40="2026-11-06T10:00:40Z"

def page(before=-1,ids=(101,102),max_id=102):
    return {
        "ok":True,"command":"scanner_candidates",
        "cursor_requested":before,"records":[
            {"id":x,"symbol":"TEST","signals":["synthetic_only"]} for x in ids
        ],
        "next_cursor":ids[-1],"max_id_at_read":max_id,
    }

def synthetic_receipt_lookup(batch_id, ids, *, wrong=False):
    def lookup(*,stage,receipt_id):
        return {
            "source":"authenticated_webui_host_terminal" if not wrong else "untrusted_chat_text",
            "stage":stage,"receipt_id":receipt_id,"batch_id":batch_id,
            "candidate_ids":list(ids),"terminal":"completed",
        }
    return lookup

class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="scanner_p1_offline_")
        self.dbfile=Path(self.temp.name)/"state.db"
        self.c=ScannerCandidateConsumer(self.dbfile,batch_size=3)
    def tearDown(self):
        self.c.close()
        self.temp.cleanup()

    def stage(self):
        batch=self.c.stage_page(page(),requested_cursor=-1,now_utc=T0)
        self.assertEqual(-1,self.c.cursor())
        return batch

    def claim(self,*,now=T1,budget=2,worker="worker-A",lease=30):
        return self.c.claim_for_model(worker_id=worker,max_calls_per_utc_day=budget,
                                      lease_seconds=lease,now_utc=now)

    def test_zero_budget_blocks_model_claim(self):
        self.stage()
        self.assertIsNone(self.claim(budget=0))
        self.assertEqual(-1,self.c.cursor())
        self.assertEqual({"pending":1},self.c.status()["batch_counts"])
        self.assertEqual(0,self.c.db.execute("SELECT count(*) FROM model_call_budget").fetchone()[0])

    def test_duplicate_page_idempotent_and_conflicting_page_rejected(self):
        first=self.stage()
        self.assertEqual(first,self.c.stage_page(page(),requested_cursor=-1,now_utc=T1))
        with self.assertRaisesRegex(ConsumerError,"unacknowledged"):
            self.c.stage_page(page(ids=(103,104),max_id=104),requested_cursor=-1,now_utc=T1)
        self.assertEqual(1,self.c.db.execute("SELECT count(*) FROM consumer_batch").fetchone()[0])
        self.assertEqual(-1,self.c.cursor())

    def test_full_two_stage_verification_and_restart(self):
        batch=self.stage()
        self.assertIsNotNone(self.claim())
        with self.assertRaisesRegex(ConsumerError,"authenticated WebUI receipt lookup"):
            self.c.record_verified_stage(batch_id=batch,worker_id="worker-A",
                stage="INVESTIGATOR",receipt_id="inv-001",candidate_ids=[101,102],now_utc=T2)
        with self.assertRaises(ConsumerError):
            self.c.acknowledge(batch_id=batch,worker_id="worker-A",
                investigator_receipt_id="inv-001",decision_receipt_id="dec-001",
                candidate_ids=[101,102],investigator_ack=True,decision_ack=True,now_utc=T2)
        self.c.receipt_lookup=synthetic_receipt_lookup(batch,[101,102])
        with self.assertRaisesRegex(ConsumerError,"precede"):
            self.c.record_verified_stage(batch_id=batch,worker_id="worker-A",stage="DECISION",
                receipt_id="dec-001",candidate_ids=[101,102],now_utc=T2)
        self.assertTrue(self.c.record_verified_stage(batch_id=batch,worker_id="worker-A",
            stage="INVESTIGATOR",receipt_id="inv-001",candidate_ids=[101,102],now_utc=T2))
        self.assertFalse(self.c.record_verified_stage(batch_id=batch,worker_id="worker-A",
            stage="INVESTIGATOR",receipt_id="inv-001",candidate_ids=[101,102],now_utc=T2))
        with self.assertRaises(ConsumerError):
            self.c.acknowledge(batch_id=batch,worker_id="worker-A",
                investigator_receipt_id="inv-001",decision_receipt_id="dec-001",
                candidate_ids=[101,102],investigator_ack=True,decision_ack=True,now_utc=T2)
        with self.assertRaisesRegex(ConsumerError,"distinct"):
            self.c.record_verified_stage(batch_id=batch,worker_id="worker-A",stage="DECISION",
                receipt_id="inv-001",candidate_ids=[101,102],now_utc=T2)
        self.assertTrue(self.c.record_verified_stage(batch_id=batch,worker_id="worker-A",
            stage="DECISION",receipt_id="dec-001",candidate_ids=[101,102],now_utc=T2))
        with self.assertRaises(ConsumerError):
            self.c.acknowledge(batch_id=batch,worker_id="worker-A",
                investigator_receipt_id="inv-001",decision_receipt_id="dec-001",
                candidate_ids=[101],investigator_ack=True,decision_ack=True,now_utc=T2)
        with self.assertRaises(ConsumerError):
            self.c.acknowledge(batch_id=batch,worker_id="worker-A",
                investigator_receipt_id="inv-001",decision_receipt_id="inv-001",
                candidate_ids=[101,102],investigator_ack=True,decision_ack=True,now_utc=T2)
        self.assertEqual(102,self.c.acknowledge(batch_id=batch,worker_id="worker-A",
            investigator_receipt_id="inv-001",decision_receipt_id="dec-001",
            candidate_ids=[101,102],investigator_ack=True,decision_ack=True,now_utc=T2))
        self.assertEqual({"INVESTIGATOR":1,"DECISION":1},self.c.status()["stage_receipt_counts"])
        self.c.close()
        self.c=ScannerCandidateConsumer(self.dbfile,batch_size=3)
        self.assertEqual(102,self.c.cursor())
        self.assertEqual({"acknowledged":1},self.c.status()["batch_counts"])
        self.assertEqual({"INVESTIGATOR":1,"DECISION":1},self.c.status()["stage_receipt_counts"])
        self.assertIsNotNone(self.c.stage_page(page(102,(103,104),104),
                                                requested_cursor=102,now_utc=T3))
        self.assertEqual(102,self.c.cursor())

    def test_forged_evidence_rejected(self):
        batch=self.stage()
        self.claim()
        self.c.receipt_lookup=synthetic_receipt_lookup(batch,[101,102],wrong=True)
        with self.assertRaisesRegex(ConsumerError,"not verified"):
            self.c.record_verified_stage(batch_id=batch,worker_id="worker-A",
                stage="INVESTIGATOR",receipt_id="fake",candidate_ids=[101,102],now_utc=T2)
        self.assertEqual(0,self.c.db.execute("SELECT count(*) FROM consumer_stage_receipt").fetchone()[0])
        self.assertEqual(-1,self.c.cursor())

    def test_expired_lease_rejects_receipts_and_recovers(self):
        batch=self.stage()
        self.claim(now=T1,lease=30)
        self.c.receipt_lookup=synthetic_receipt_lookup(batch,[101,102])
        with self.assertRaisesRegex(ConsumerError,"expired"):
            self.c.record_verified_stage(batch_id=batch,worker_id="worker-A",
                stage="INVESTIGATOR",receipt_id="late",candidate_ids=[101,102],now_utc=T40)
        new=self.claim(now=T40,budget=2,worker="worker-B")
        self.assertEqual("worker-B",new["lease_owner"])
        self.assertEqual(2,new["attempts"])
        with self.assertRaisesRegex(ConsumerError,"not owned"):
            self.c.acknowledge(batch_id=batch,worker_id="worker-A",
                investigator_receipt_id="inv",decision_receipt_id="dec",
                candidate_ids=[101,102],investigator_ack=True,decision_ack=True,now_utc=T40)
        self.assertEqual(-1,self.c.cursor())

    def test_exhausted_lease_becomes_failed(self):
        self.c.close()
        self.c=ScannerCandidateConsumer(self.dbfile,batch_size=3,max_attempts=1)
        batch=self.stage()
        self.claim(now=T1,budget=3,lease=30)
        self.assertIsNone(self.claim(now=T40,budget=3,worker="worker-B"))
        self.assertEqual({"failed":1},self.c.status()["batch_counts"])
        self.assertEqual(-1,self.c.cursor())
        self.assertIsNone(self.c.pending_batch(now_utc=T40))

    def test_retry_backoff_and_restart(self):
        batch=self.stage()
        self.claim(now=T1,budget=3)
        self.assertEqual("retry_wait",self.c.fail(batch_id=batch,worker_id="worker-A",
                   error_type="synthetic_transport_failure",now_utc=T2))
        self.assertIsNone(self.c.pending_batch(now_utc=T3))
        self.c.close()
        self.c=ScannerCandidateConsumer(self.dbfile,batch_size=3)
        self.assertIsNotNone(self.c.pending_batch(now_utc=T40))
        self.assertIsNotNone(self.claim(now=T40,budget=3,worker="worker-B"))
        self.assertEqual(-1,self.c.cursor())

    def test_bounds_and_empty_poll(self):
        self.assertIsNone(self.c.stage_page({
            "ok":True,"command":"scanner_candidates","cursor_requested":-1,
            "records":[],"next_cursor":0,"max_id_at_read":0
        },requested_cursor=-1,now_utc=T0))
        self.assertEqual(-1,self.c.cursor())
        with self.assertRaises(ConsumerError):
            self.c.stage_page(page(ids=(4,3),max_id=4),requested_cursor=-1,now_utc=T1)
        with self.assertRaises(ConsumerError):
            self.c.stage_page(page(ids=(1,2,3,4),max_id=4),requested_cursor=-1,now_utc=T1)

class ExistingBridgeDispatchTests(unittest.TestCase):
    def test_scanner_candidates_forwarded_with_cursor_and_page_limit(self):
        from unittest.mock import patch
        from runtime.deepseek.host_command_bridge import execute, COMMANDS
        self.assertIn("scanner_candidates", COMMANDS)
        with patch("runtime.deepseek.scanner_read_commands.scanner_candidates",
                   return_value={"ok":True,"records":[]}) as handler:
            response=execute("scanner_candidates",cursor=501,limit=7)
            self.assertTrue(response["ok"])
            handler.assert_called_once_with(cursor=501,limit=7)

    def test_scanner_health_is_allowed_fixed_command(self):
        from unittest.mock import patch
        from runtime.deepseek.host_command_bridge import execute, COMMANDS
        self.assertIn("scanner_health", COMMANDS)
        with patch("runtime.deepseek.scanner_read_commands.scanner_health",
                   return_value={"ok":True,"health_fresh":True}) as handler:
            response=execute("scanner_health")
            self.assertTrue(response["health_fresh"])
            handler.assert_called_once_with()


if __name__=="__main__":
    unittest.main()

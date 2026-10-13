"""Lease races and real local-process crash recovery; no provider/broker calls."""
import json
import multiprocessing
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from openwebui.tools.catalyst_handoff_queue import CatalystHandoffQueue
from worker.run_catalyst_consumer import consume, flush_review_outbox
from worker import run_catalyst_consumer as worker
from test_catalyst_consumer import candidate, result, StaticReviewer

NOW = datetime(2026, 10, 11, 14, 30, tzinfo=timezone.utc)

def export_then_crash(queue_path, log_path):
    queue = CatalystHandoffQueue(queue_path)
    queue.mark_review_exported = lambda *args, **kwargs: os._exit(37)
    flush_review_outbox(queue, Path(log_path))

def export(queue_path, log_path):
    flush_review_outbox(CatalystHandoffQueue(queue_path), Path(log_path))

def complete_then_crash(queue_path):
    queue = CatalystHandoffQueue(queue_path)
    event = queue.pending(now=NOW)[0]
    claim = queue.claim(event['id'], now=NOW)
    queue.acknowledge(event['id'], result=result('ABC'), lease_token=claim['lease_token'], now=NOW)
    os._exit(38)

def crash_during_log_replace(queue_path, log_path, after_replace):
    original_replace = Path.replace
    def crash(source, target):
        if Path(target) == Path(log_path):
            if after_replace:
                original_replace(source, target)
            os._exit(39)
        return original_replace(source, target)
    with patch.object(Path, 'replace', crash):
        flush_review_outbox(CatalystHandoffQueue(queue_path), Path(log_path))

class Recovery(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.queue_path = Path(self.temp.name)/'queue.jsonl'
        self.log_path = Path(self.temp.name)/'reviews.jsonl'
        self.queue = CatalystHandoffQueue(self.queue_path)
        self.event = self.queue.enqueue(candidate('ABC'), now=NOW)['event']

    def done(self):
        claim = self.queue.claim(self.event['id'], now=NOW)
        return self.queue.acknowledge(self.event['id'], result=result('ABC'), lease_token=claim['lease_token'], now=NOW)

    def process(self, target, *args, expected=0):
        child = multiprocessing.Process(target=target, args=args)
        child.start(); child.join(10)
        self.assertFalse(child.is_alive())
        self.assertEqual(child.exitcode, expected)

    def test_old_claim_cannot_acknowledge_or_retry_reassigned_work(self):
        old = self.queue.claim(self.event['id'], lease_seconds=1, now=NOW)
        later = NOW + timedelta(seconds=2)
        new = self.queue.claim(self.event['id'], now=later)
        self.assertNotEqual(old['lease_token'], new['lease_token'])
        before = self.queue_path.read_bytes()
        self.assertIsNone(self.queue.acknowledge(self.event['id'], result={'wrong':True}, lease_token=old['lease_token'], now=later))
        self.assertIsNone(self.queue.retry(self.event['id'], error='old worker', lease_token=old['lease_token'], now=later))
        self.assertEqual(self.queue_path.read_bytes(), before)
        self.assertIsNotNone(self.queue.acknowledge(self.event['id'], result=result('ABC'), lease_token=new['lease_token'], now=later))

    def test_expired_or_missing_token_cannot_commit(self):
        claim = self.queue.claim(self.event['id'], lease_seconds=1, now=NOW)
        for token, when in ((None,NOW),('wrong',NOW),(claim['lease_token'],NOW+timedelta(seconds=1))):
            with self.subTest(token=token):
                self.assertIsNone(self.queue.acknowledge(self.event['id'], result=result('ABC'), lease_token=token, now=when))
        self.assertEqual(self.queue.pending_reviews(), [])

    def test_slow_reviewer_never_reports_false_completion(self):
        times = iter([NOW,NOW,NOW+timedelta(seconds=2),NOW+timedelta(seconds=2)])
        output = consume(self.queue,StaticReviewer(),lease_seconds=1,clock=lambda:next(times))
        self.assertEqual(output['completed'], [])
        self.assertEqual(len(output['lease_lost']), 1)
        self.assertEqual(self.queue.pending_reviews(), [])

    def test_result_and_outbox_survive_process_exit_before_export(self):
        self.process(complete_then_crash,str(self.queue_path),expected=38)
        self.assertFalse(self.log_path.exists())
        recovered=flush_review_outbox(CatalystHandoffQueue(self.queue_path),self.log_path)
        self.assertEqual(recovered['delivered'],1)
        self.assertEqual(len(self.log_path.read_text().splitlines()),1)
        self.assertEqual(self.queue.pending_reviews(),[])

    def test_crash_after_log_commit_before_marker_is_idempotent(self):
        self.done()
        self.process(export_then_crash,str(self.queue_path),str(self.log_path),expected=37)
        self.assertEqual(len(self.queue.pending_reviews()),1)
        recovered=flush_review_outbox(CatalystHandoffQueue(self.queue_path),self.log_path)
        self.assertEqual(recovered,{'delivered':0,'replayed':1})
        self.assertEqual(len(self.log_path.read_text().splitlines()),1)
        self.assertEqual(self.queue.pending_reviews(),[])

    def test_concurrent_exporters_write_one_receipt(self):
        self.done()
        children=[multiprocessing.Process(target=export,args=(str(self.queue_path),str(self.log_path))) for _ in range(4)]
        for child in children:child.start()
        for child in children:
            child.join(10); self.assertFalse(child.is_alive()); self.assertEqual(child.exitcode,0)
        self.assertEqual(len(self.log_path.read_text().splitlines()),1)
        self.assertEqual(self.queue.pending_reviews(),[])

    def test_legacy_done_record_and_existing_log_recover_without_duplication(self):
        row=self.done(); row.pop('review_outbox')
        self.queue_path.write_text(json.dumps(row)+'\n')
        legacy=self.queue._review_receipt(row);legacy.pop('receipt_id');legacy['reviewed_at']='legacy-export-time'
        self.log_path.write_text(json.dumps(legacy)+'\n')
        self.assertEqual(flush_review_outbox(self.queue,self.log_path),{'delivered':0,'replayed':1})
        self.assertEqual(len(self.log_path.read_text().splitlines()),1)

    def test_corrupt_queue_blocks_mutation_without_erasing_evidence(self):
        with self.queue_path.open('a') as handle:handle.write('{torn-record')
        before=self.queue_path.read_bytes()
        with self.assertRaises(ValueError):self.queue.enqueue(candidate('OTHER'),now=NOW)
        self.assertEqual(self.queue_path.read_bytes(),before)

    def test_corrupt_or_conflicting_log_does_not_mark_exported(self):
        self.done()
        for contents in ('{torn',json.dumps({'event_id':self.event['id'],'result':{'different':True}})+'\n'):
            with self.subTest(contents=contents):
                self.log_path.write_text(contents)
                with self.assertRaises(ValueError):flush_review_outbox(self.queue,self.log_path)
                self.assertEqual(self.log_path.read_text(),contents)
                self.assertEqual(len(self.queue.pending_reviews()),1)

    def test_valid_first_receipt_cannot_hide_corrupt_or_conflicting_suffix(self):
        row = self.done()
        receipt = self.queue._review_receipt(row)
        for suffix in ('{torn', json.dumps({**receipt, 'result': {'conflicting': True}}), json.dumps(receipt)):
            with self.subTest(suffix=suffix):
                contents = json.dumps(receipt) + '\n' + suffix + '\n'
                self.log_path.write_text(contents)
                with self.assertRaises(ValueError):
                    flush_review_outbox(self.queue, self.log_path)
                self.assertEqual(self.log_path.read_text(), contents)
                self.assertEqual(len(self.queue.pending_reviews()), 1)

    def test_wrong_explicit_receipt_identity_cannot_ack_by_matching_event(self):
        row = self.done()
        receipt = self.queue._review_receipt(row)
        receipt['receipt_id'] = 'catalyst-review:wrong-event'
        contents = json.dumps(receipt) + '\n'
        self.log_path.write_text(contents)
        with self.assertRaises(ValueError):
            flush_review_outbox(self.queue, self.log_path)
        self.assertEqual(self.log_path.read_text(), contents)
        self.assertEqual(len(self.queue.pending_reviews()), 1)

    def test_tampered_outbox_cannot_project_another_event_or_changed_result(self):
        original = self.done()
        for change in ({'event_id': 'another-event'}, {'result': {'forged': True}}, {'receipt_id': 'wrong-receipt'}):
            with self.subTest(change=change):
                row = json.loads(json.dumps(original))
                row['review_outbox'].update(change)
                contents = json.dumps(row) + '\n'
                self.queue_path.write_text(contents)
                with self.assertRaises(ValueError):
                    flush_review_outbox(self.queue, self.log_path)
                self.assertEqual(self.queue_path.read_text(), contents)
                self.assertFalse(self.log_path.exists())

    def test_failed_replace_preserves_queue_and_recovery_intent(self):
        self.done()
        with patch.object(Path,'replace',side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError):flush_review_outbox(self.queue,self.log_path)
        self.assertFalse(self.log_path.exists())
        self.assertEqual(len(self.queue.pending_reviews()),1)
        self.assertEqual(flush_review_outbox(self.queue,self.log_path)['delivered'],1)

    def test_expired_crashes_cannot_repeat_provider_work_without_bound(self):
        for attempt in range(3):
            claim=self.queue.claim(self.event['id'],lease_seconds=1,max_attempts=3,now=NOW+timedelta(seconds=attempt*2))
            self.assertIsNotNone(claim)
        self.assertIsNone(self.queue.claim(self.event['id'],max_attempts=3,now=NOW+timedelta(seconds=6)))
        row=self.queue._read()[0]
        self.assertEqual(row['status'],'failed')
        self.assertEqual(row['attempts'],3)
        self.assertEqual(self.queue.pending(now=NOW+timedelta(seconds=6)),[])

    def test_main_recovers_local_outbox_outside_session_without_provider(self):
        self.done()
        decision=SimpleNamespace(allowed=False,reason='weekend',to_dict=lambda:{'allowed':False})
        with patch.object(worker,'QUEUE_PATH',self.queue_path), patch.object(worker,'REVIEW_LOG',self.log_path), patch.object(worker,'evaluate_session',return_value=decision), patch.object(worker,'_write_status') as status, patch.object(worker,'OpenAICompatibleReviewer',side_effect=AssertionError('provider must not be constructed')):
            self.assertEqual(worker.main(),0)
        self.assertEqual(status.call_args.args[0]['review_recovery']['delivered'],1)
        self.assertEqual(self.queue.pending_reviews(),[])

    def test_retry_claims_consume_daily_budget_and_resume_next_day(self):
        queue=CatalystHandoffQueue(self.queue_path,max_per_day=2)
        for attempt in range(2):
            claim=queue.claim(self.event['id'],now=NOW+timedelta(seconds=attempt),max_attempts=5)
            queue.retry(self.event['id'],error='offline provider failure',lease_token=claim['lease_token'],max_attempts=5,now=NOW+timedelta(seconds=attempt))
        self.assertIsNone(queue.claim(self.event['id'],now=NOW+timedelta(seconds=3),max_attempts=5))
        self.assertEqual(queue.stats(now=NOW)['review_attempts_today'],2)
        self.assertEqual(queue._read()[0]['status'],'pending')
        self.assertIsNotNone(queue.claim(self.event['id'],now=NOW+timedelta(days=1),max_attempts=5))
        self.assertEqual(queue.stats(now=NOW+timedelta(days=1))['review_attempts_today'],1)

    def test_legacy_claims_cannot_reset_daily_attempt_budget(self):
        claim=self.queue.claim(self.event['id'],now=NOW,lease_seconds=1)
        rows=self.queue._read();rows[0].pop('review_attempts_by_date');rows[0]['attempts']=2
        self.queue_path.write_text(json.dumps(rows[0])+'\n')
        queue=CatalystHandoffQueue(self.queue_path,max_per_day=2)
        self.assertIsNone(queue.claim(claim['id'],now=NOW+timedelta(seconds=2),max_attempts=5))
        self.assertEqual(queue.stats(now=NOW)['review_attempts_today'],2)

    def test_legacy_attempts_are_preserved_when_new_accounting_starts(self):
        self.queue.claim(self.event['id'],now=NOW,lease_seconds=1)
        rows=self.queue._read();rows[0].pop('review_attempts_by_date');rows[0]['attempts']=2
        self.queue_path.write_text(json.dumps(rows[0])+'\n')
        queue=CatalystHandoffQueue(self.queue_path,max_per_day=5)
        self.assertIsNotNone(queue.claim(self.event['id'],now=NOW+timedelta(seconds=2),max_attempts=5))
        self.assertEqual(queue.stats(now=NOW)['review_attempts_today'],3)

    def test_process_death_before_and_after_atomic_log_replace_recovers(self):
        self.done()
        for after in (False,True):
            with self.subTest(after=after):
                self.process(crash_during_log_replace,str(self.queue_path),str(self.log_path),after,expected=39)
                self.assertEqual(len(self.queue.pending_reviews()),1)
        self.assertEqual(flush_review_outbox(self.queue,self.log_path),{'delivered':0,'replayed':1})
        self.assertEqual(len(self.log_path.read_text().splitlines()),1)

    def test_recovery_cli_is_provider_free_and_replay_safe(self):
        self.done()
        script=Path(worker.__file__)
        command=[sys.executable,str(script),'--recover-reviews-only','--queue',str(self.queue_path),'--review-log',str(self.log_path)]
        first=subprocess.run(command,check=True,capture_output=True,text=True,timeout=10)
        second=subprocess.run(command,check=True,capture_output=True,text=True,timeout=10)
        self.assertEqual(json.loads(first.stdout)['delivered'],1)
        self.assertEqual(json.loads(first.stdout)['provider_calls'],0)
        self.assertEqual(json.loads(second.stdout)['delivered'],0)
        self.assertEqual(len(self.log_path.read_text().splitlines()),1)

if __name__=='__main__':unittest.main()


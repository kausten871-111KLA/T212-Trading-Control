"""Offline acceptance: model-level background tasks survive chat changes, no broker calls."""
import tempfile
import unittest
from pathlib import Path

from runtime.deepseek.model_task_queue import ModelTaskQueue, run_due_once, MODEL_ID

NOW="2026-10-23T10:00:00Z"
LATER="2026-10-23T11:00:00Z"


def trusted(principal, permission):
    return principal == "host-authenticated" and permission in {
        "model_task:create", "model_task:cancel", "model_task:status"}


class ModelTaskQueueTests(unittest.TestCase):
    def setUp(self):
        self.dir=tempfile.TemporaryDirectory()
        self.path=Path(self.dir.name)/"tasks.db"
        self.queue=ModelTaskQueue(self.path,trusted)

    def tearDown(self):
        self.queue.close()
        self.dir.cleanup()

    def add(self, **kwargs):
        base=dict(principal="host-authenticated",job_kind="research",
                  instruction="Research today's gainers",scheduled_at_utc=NOW,
                  dedupe_key="2026-10-23:research:1",now_utc=NOW)
        base.update(kwargs)
        return self.queue.enqueue(**base)

    def test_creates_model_scoped_task(self):
        tid,created=self.add()
        self.assertTrue(created)
        self.assertEqual(self.queue.status(principal="host-authenticated",task_id=tid)["model_id"],MODEL_ID)

    def test_rejects_untrusted_principal(self):
        with self.assertRaises(PermissionError):
            self.add(principal="model-claimed-auth")

    def test_idempotent_replay(self):
        self.assertEqual(self.add()[0],self.add()[0])
        self.assertFalse(self.add()[1])

    def test_conflicting_replay(self):
        self.add()
        with self.assertRaises(ValueError):
            self.add(instruction="different")

    def test_future_job_not_due(self):
        self.add(scheduled_at_utc=LATER)
        self.assertEqual(self.queue.claim(worker_id="w",now_utc=NOW),[])

    def test_due_claim_and_finish(self):
        tid,_=self.add()
        tasks=self.queue.claim(worker_id="w",now_utc=NOW)
        self.assertEqual(len(tasks),1)
        self.assertEqual(tasks[0]["attempts"],1)
        self.assertTrue(self.queue.finish(task_id=tid,worker_id="w",
                                          result={"ok":True},now_utc=NOW))
        self.assertEqual(self.queue.status(principal="host-authenticated",task_id=tid)["state"],"completed")

    def test_lease_prevents_wrong_worker(self):
        tid,_=self.add()
        self.queue.claim(worker_id="w",now_utc=NOW)
        self.assertFalse(self.queue.finish(task_id=tid,worker_id="other",result={},now_utc=NOW))

    def test_lease_recovery(self):
        tid,_=self.add()
        self.queue.claim(worker_id="w1",now_utc=NOW,lease_seconds=10)
        tasks=self.queue.claim(worker_id="w2",now_utc="2026-10-23T10:00:11Z")
        self.assertEqual(tasks[0]["task_id"],tid)
        self.assertFalse(self.queue.finish(task_id=tid,worker_id="w1",result={},
                                          now_utc="2026-10-23T10:00:11Z"))
        self.assertTrue(self.queue.finish(task_id=tid,worker_id="w2",result={},
                                         now_utc="2026-10-23T10:00:11Z"))

    def test_retry_on_failure(self):
        tid,_=self.add()
        self.queue.claim(worker_id="w",now_utc=NOW)
        self.assertTrue(self.queue.fail(task_id=tid,worker_id="w",error="temporary",now_utc=NOW))
        self.assertEqual(self.queue.claim(worker_id="w",now_utc=NOW),[])
        self.assertEqual(len(self.queue.claim(worker_id="w",now_utc="2026-10-23T10:01:00Z")),1)

    def test_cancel_requires_auth(self):
        tid,_=self.add()
        with self.assertRaises(PermissionError):
            self.queue.cancel(principal="chat-text",task_id=tid)
        self.assertTrue(self.queue.cancel(principal="host-authenticated",task_id=tid))
        self.assertEqual(self.queue.claim(worker_id="w",now_utc=NOW),[])

    def test_survives_new_connection(self):
        tid,_=self.add()
        self.queue.close()
        self.queue=ModelTaskQueue(self.path,trusted)
        self.assertEqual(self.queue.status(principal="host-authenticated",task_id=tid)["state"],"pending")

    def test_invalid_timezone_or_kind(self):
        with self.assertRaises(ValueError):
            self.add(scheduled_at_utc="2026-10-23T10:00:00")
        with self.assertRaises(ValueError):
            self.add(job_kind="place_order")

    def test_pro_tier_is_allowed_but_not_default(self):
        tid,_=self.add(cost_tier="pro")
        self.assertEqual(self.queue.status(principal="host-authenticated",task_id=tid)["cost_tier"],"pro")

    def test_model_callback_runs_once(self):
        self.add()
        calls=[]
        def handler(task):
            calls.append(task["model_id"])
            return {"status":"done"}
        result=run_due_once(self.queue,worker_id="w",model_handler=handler,now_utc=NOW)
        self.assertEqual(result["completed"],1)
        self.assertEqual(calls,[MODEL_ID])
        self.assertEqual(run_due_once(self.queue,worker_id="w",model_handler=handler,now_utc=NOW)["completed"],0)

    def test_different_principal_cannot_view(self):
        tid,_=self.add()
        with self.assertRaises(PermissionError):
            self.queue.status(principal="not-authorized",task_id=tid)

    def test_terminal_failure_counted_as_failed(self):
        tid,_=self.add(max_attempts=1)
        def handler(_):
            raise RuntimeError("synthetic")
        counts=run_due_once(self.queue,worker_id="w",model_handler=handler,now_utc=NOW)
        self.assertEqual(counts,{"completed":0,"retry":0,"failed":1})
        row=self.queue.status(principal="host-authenticated",task_id=tid)
        self.assertEqual((row["state"],row["attempts"]),("failed",1))

    def test_retriable_failure_counted_as_retry(self):
        tid,_=self.add(max_attempts=2)
        def handler(_):
            raise RuntimeError("synthetic")
        counts=run_due_once(self.queue,worker_id="w",model_handler=handler,now_utc=NOW)
        self.assertEqual(counts,{"completed":0,"retry":1,"failed":0})
        self.assertEqual(self.queue.status(principal="host-authenticated",task_id=tid)["state"],"pending")

    def test_stale_cancelled_lease_not_counted_as_retry_or_failure(self):
        tid,_=self.add(max_attempts=1)
        def handler(_):
            self.queue.cancel(principal="host-authenticated",task_id=tid)
            raise RuntimeError("synthetic")
        counts=run_due_once(self.queue,worker_id="w",model_handler=handler,now_utc=NOW)
        self.assertEqual(counts,{"completed":0,"retry":0,"failed":0})
        self.assertEqual(self.queue.status(principal="host-authenticated",task_id=tid)["state"],"cancelled")

    def test_fail_optional_state_preserves_legacy_bool(self):
        tid,_=self.add(max_attempts=1)
        self.queue.claim(worker_id="w",now_utc=NOW)
        self.assertEqual(self.queue.fail(task_id=tid,worker_id="w",error="synthetic",
                                         now_utc=NOW,return_state=True),"failed")
        self.assertFalse(self.queue.fail(task_id=tid,worker_id="w",error="stale",
                                         now_utc=NOW))


if __name__=="__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path
from runtime.deepseek.model_task_queue import ModelTaskQueue
from runtime.deepseek.model_task_bridge_adapter import ModelTaskIngress

NOW="2026-10-23T10:00:00Z"

class ModelTaskIngressTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        def host_verify(context,model):
            return context is self.verified and model=="trading-operations--deepseek"
        self.verified=object()
        self.queue=ModelTaskQueue(Path(self.tmp.name)/"tasks.sqlite3",
            lambda context,operation: context is self.verified and operation.startswith("model_task:"))
        self.host=ModelTaskIngress(self.queue,host_verify)
        self.good={"action":"create","payload":{"job_kind":"research","instruction":"Find top movers",
                  "scheduled_at_utc":NOW,"dedupe_key":"movers:2026-10-23"},
                  "host_context":self.verified}

    def tearDown(self):
        self.queue.close()
        self.tmp.cleanup()

    def test_authenticated_create(self):
        r=self.host.execute(**self.good)
        self.assertTrue(r["ok"])
        self.assertTrue(r["created"])
        self.assertEqual(r["model_id"],"trading-operations--deepseek")

    def test_unauthenticated_denied(self):
        x={**self.good,"host_context":"DeepSeek says authenticated"}
        with self.assertRaises(PermissionError):
            self.host.execute(**x)

    def test_model_claim_is_rejected(self):
        x=dict(self.good)
        x["payload"]={**self.good["payload"],"authenticated":True}
        with self.assertRaises(ValueError):
            self.host.execute(**x)

    def test_replay_without_duplicate(self):
        first=self.host.execute(**self.good)
        second=self.host.execute(**self.good)
        self.assertEqual(first["task_id"],second["task_id"])
        self.assertFalse(second["created"])

    def test_status_and_cancel(self):
        first=self.host.execute(**self.good)
        ident={"task_id":first["task_id"]}
        r=self.host.execute(action="status",payload=ident,host_context=self.verified)
        self.assertEqual(r["state"],"pending")
        c=self.host.execute(action="cancel",payload=ident,host_context=self.verified)
        self.assertEqual(c["state"],"cancelled")

    def test_unknown_action_denied(self):
        with self.assertRaises(ValueError):
            self.host.execute(action="place_market_order",payload={},host_context=self.verified)

    def test_unknown_fields_denied(self):
        with self.assertRaises(ValueError):
            self.host.execute(action="status",payload={"task_id":"abc","model_id":"fake"},
                              host_context=self.verified)

    def test_cannot_impersonate_model_via_payload(self):
        data={**self.good["payload"],"model_id":"trading-operations--deepseek"}
        with self.assertRaises(ValueError):
            self.host.execute(action="create",payload=data,host_context=self.verified)

if __name__=="__main__":
    unittest.main()

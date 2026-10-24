import tempfile
import unittest
from pathlib import Path
from runtime.deepseek.model_task_queue import ModelTaskQueue
from runtime.deepseek.model_task_worker_adapter import DeepSeekTaskHandler, run_existing_worker_cycle

NOW="2026-10-23T13:00:00Z"
ROUTES={"light":"configured-low-cost-provider-model","pro":"configured-reasoning-provider-model"}

class WorkerAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.principal=object()
        self.queue=ModelTaskQueue(Path(self.tmp.name)/"tasks.sqlite3",
          lambda p,perm: p is self.principal)
        self.calls=[]
        def invoke_model(**kwargs):
            self.calls.append(kwargs)
            return {"ok":True,"response":"accepted","usage":{"total_tokens":10},
                    "provider_request_id":"mock-req"}
        self.invoke=invoke_model

    def tearDown(self):
        self.queue.close()
        self.tmp.cleanup()

    def add(self,tier="light",key="1"):
        return self.queue.enqueue(principal=self.principal,job_kind="analysis",
                                  instruction="Analyse watchlist",scheduled_at_utc=NOW,
                                  dedupe_key=key,cost_tier=tier,now_utc=NOW)

    def test_light_routing(self):
        self.add()
        result=run_existing_worker_cycle(self.queue,worker_id="existing-worker",
          invoke_model=self.invoke,model_routes=ROUTES,now_utc=NOW)
        self.assertEqual(result["completed"],1)
        self.assertEqual(self.calls[0]["model_id"],ROUTES["light"])

    def test_pro_routing_when_configured(self):
        self.add("pro")
        result=run_existing_worker_cycle(self.queue,worker_id="existing-worker",
          invoke_model=self.invoke,model_routes=ROUTES,allow_pro=True,now_utc=NOW)
        self.assertEqual(result["completed"],1)
        self.assertEqual(self.calls[0]["model_id"],ROUTES["pro"])

    def test_pro_block_when_host_not_enabled(self):
        self.add("pro")
        result=run_existing_worker_cycle(self.queue,worker_id="existing-worker",
          invoke_model=self.invoke,model_routes=ROUTES,allow_pro=False,now_utc=NOW)
        self.assertEqual(result["retry"],1)
        self.assertEqual(self.calls,[])

    def test_pro_denied_by_default_in_existing_worker(self):
        self.add("pro")
        result=run_existing_worker_cycle(self.queue,worker_id="existing-worker",
          invoke_model=self.invoke,model_routes=ROUTES,now_utc=NOW)
        self.assertEqual(result["retry"],1)
        self.assertEqual(self.calls,[])

    def test_pro_denied_by_default_in_direct_handler(self):
        handler=DeepSeekTaskHandler(invoke_model=self.invoke,model_routes=ROUTES)
        with self.assertRaises(PermissionError):
            handler({"model_id":"trading-operations--deepseek","cost_tier":"pro",
                     "job_kind":"analysis","instruction":"mock","task_id":"synthetic"})
        self.assertEqual(self.calls,[])

    def test_no_provider_model_guessing(self):
        with self.assertRaises(ValueError):
            DeepSeekTaskHandler(invoke_model=self.invoke,model_routes={"light":"a"})

    def test_cannot_impersonate_owner(self):
        handler=DeepSeekTaskHandler(invoke_model=self.invoke,model_routes=ROUTES)
        with self.assertRaises(PermissionError):
            handler({"model_id":"other","cost_tier":"light"})

    def test_fails_closed_on_provider_error(self):
        self.add()
        result=run_existing_worker_cycle(self.queue,worker_id="existing-worker",
          invoke_model=lambda **kw:{"ok":False},model_routes=ROUTES,now_utc=NOW)
        self.assertEqual(result["retry"],1)

    def test_idempotent_complete(self):
        self.add()
        for _ in range(2):
            run_existing_worker_cycle(self.queue,worker_id="existing-worker",
              invoke_model=self.invoke,model_routes=ROUTES,now_utc=NOW)
        self.assertEqual(len(self.calls),1)

    def test_usage_persisted_without_chat(self):
        task_id,_=self.add()
        run_existing_worker_cycle(self.queue,worker_id="existing-worker",
          invoke_model=self.invoke,model_routes=ROUTES,now_utc=NOW)
        status=self.queue.status(principal=self.principal,task_id=task_id)
        self.assertIn('"total_tokens":10',status["result_json"])

if __name__=="__main__":
    unittest.main()

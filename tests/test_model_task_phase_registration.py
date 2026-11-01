import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from runtime.deepseek.model_task_queue import ModelTaskQueue
from runtime.deepseek.model_task_phase_registration import SupervisedModelTaskCycle
from runtime.deepseek.service import PhaseService, migrate

NOW="2026-10-23T14:00:00+00:00"


class ModelTaskPhaseRegistrationTests(unittest.TestCase):
    def setup_task(self,path,tier="light"):
        trusted=object()
        q=ModelTaskQueue(path, authorizer=lambda p,permission:p is trusted)
        task_id,_=q.enqueue(principal=trusted,job_kind="research",
              instruction="Synthetic test only, no external market calls",
              scheduled_at_utc=NOW,dedupe_key="synthetic-"+tier,cost_tier=tier)
        q.close()
        return trusted,task_id

    def test_synthetic_task_completed_by_existing_supervised_phase(self):
        with tempfile.TemporaryDirectory() as directory:
            phase_path=Path(directory)/"phase.sqlite3"
            queue_path=Path(directory)/"model_tasks.sqlite3"
            migrate(phase_path)
            trusted,task_id=self.setup_task(queue_path)
            invoked=[]
            def fake_inference(**kwargs):
                invoked.append(kwargs)
                return {"ok":True,"response":"synthetic completion",
                        "usage":{"input_tokens":0,"output_tokens":0},
                        "provider_request_id":"TEST-ONLY"}
            cycle=SupervisedModelTaskCycle(
                db_path=queue_path,worker_id="existing-phase-worker",
                invoke_model=fake_inference,
                model_routes={"light":"fake-light","pro":"fake-pro"})
            with contextlib.redirect_stdout(io.StringIO()):
                PhaseService(phase_path,model_task_cycle=cycle).run(once=True)
            self.assertEqual(len(invoked),1)
            self.assertEqual(invoked[0]["model_id"],"fake-light")
            q=ModelTaskQueue(queue_path,authorizer=lambda p,permission:p is trusted)
            try:
                row=q.status(principal=trusted,task_id=task_id)
                self.assertEqual(row["state"],"completed")
                self.assertIn("synthetic completion",row["result_json"])
            finally:q.close()

    def test_no_paid_pro_without_opt_in(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/"tasks.sqlite3"
            trusted,task_id=self.setup_task(p,tier="pro")
            invoked=[]
            cycle=SupervisedModelTaskCycle(db_path=p,worker_id="phase",
                   invoke_model=lambda **kwargs:invoked.append(kwargs) or {"ok":True},
                   model_routes={"light":"light","pro":"pro"},allow_pro=False)
            result=cycle()
            self.assertEqual(invoked,[])
            self.assertEqual(result["retry"],1)
            q=ModelTaskQueue(p,authorizer=lambda principal,permission:principal is trusted)
            try:self.assertEqual(q.status(principal=trusted,task_id=task_id)["state"],"pending")
            finally:q.close()

    def test_missing_host_inference_refused(self):
        with self.assertRaises(ValueError):
            SupervisedModelTaskCycle(db_path="/tmp/unused",worker_id="phase",
                 invoke_model=None,model_routes={"light":"light","pro":"pro"})


if __name__=="__main__":
    unittest.main()

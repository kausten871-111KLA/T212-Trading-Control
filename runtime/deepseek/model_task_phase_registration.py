"""Bridge trusted model inference to the EXISTING phase service's injected hook.

This is a callback factory, NOT a daemon, timer, broker or live inference
implementation. The host must explicitly inject its authenticated inference
callback with the full Trading Operations owner context and eligible tools.
"""
from pathlib import Path

from .model_task_queue import ModelTaskQueue
from .model_task_worker_adapter import run_existing_worker_cycle


class SupervisedModelTaskCycle:
    """Callable intended for PhaseService(model_task_cycle=...).

    The existing phase service invokes it once per poll interval when enabled.
    An absent model inference callback is a configuration error, not an
    invitation to fall back to a provider API or infer account credentials.
    """
    def __init__(self, *, db_path, worker_id, invoke_model, model_routes,
                 allow_pro=False):
        if not callable(invoke_model):
            raise ValueError("Trusted WebUI-owner-context inference required")
        if not isinstance(worker_id,str) or not worker_id.strip():
            raise ValueError("Explicit stable worker ID required")
        self.db_path=Path(db_path)
        self.worker_id=worker_id
        self.invoke_model=invoke_model
        self.model_routes=dict(model_routes)
        self.allow_pro=allow_pro

    def __call__(self):
        # Only the separately authenticated host bridge may CREATE/STATUS/
        # CANCEL tasks. The worker itself has no user-task authorization.
        queue=ModelTaskQueue(self.db_path,authorizer=lambda *_: False)
        try:
            return run_existing_worker_cycle(
                queue,
                worker_id=self.worker_id,
                invoke_model=self.invoke_model,
                model_routes=self.model_routes,
                allow_pro=self.allow_pro,
            )
        finally:
            queue.close()

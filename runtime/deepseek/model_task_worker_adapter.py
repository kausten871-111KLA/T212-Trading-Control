"""Injected DeepSeek inference callback for the EXISTING background worker.

No new daemon/scheduler or broker. The host must provide its already-configured
WebUI inference function and explicit model routing map; this code does not
know or guess provider model IDs, credentials, pricing or user chat IDs.
"""
from .model_task_queue import MODEL_ID, TIERS, run_due_once


class DeepSeekTaskHandler:
    def __init__(self, *, invoke_model, model_routes, allow_pro=True):
        if not callable(invoke_model):
            raise ValueError("Existing authenticated inference callback required")
        if not isinstance(model_routes,dict) or set(model_routes)!=TIERS:
            raise ValueError("Configure explicit light/pro model routing")
        if not all(isinstance(v,str) and v.strip() for v in model_routes.values()):
            raise ValueError("Actual provider model IDs must be configured")
        self.invoke_model=invoke_model
        self.model_routes=dict(model_routes)
        self.allow_pro=allow_pro

    def __call__(self, task):
        if task.get("model_id")!=MODEL_ID:
            raise PermissionError("Wrong owner model")
        tier=task.get("cost_tier")
        if tier not in TIERS:
            raise ValueError("Unknown model cost tier")
        if tier=="pro" and not self.allow_pro:
            raise PermissionError("Pro inference not enabled in host config")
        if task.get("job_kind") not in {"research","analysis","engineering","review"}:
            raise ValueError("Not a background research task")
        provider_model=self.model_routes[tier]
        result=self.invoke_model(
            model_id=provider_model,
            instruction=task["instruction"],
            task_id=task["task_id"],
            job_kind=task["job_kind"],
        )
        if not isinstance(result,dict) or result.get("ok") is not True:
            raise RuntimeError("Authenticated inference callback failed")
        return {
            "ok":True,
            "owner_model_id":MODEL_ID,
            "inference_model_id":provider_model,
            "tier":tier,
            "response":result.get("response"),
            "usage":result.get("usage"),
            "provider_request_id":result.get("provider_request_id"),
        }


def run_existing_worker_cycle(queue, *, worker_id, invoke_model, model_routes,
                              allow_pro=True, now_utc=None):
    """Call only from the existing host controller's supervised cycle.

    Running this function is NOT evidence that WebUI background inference is
    deployed; production host must register the callback and schedule calls.
    """
    handler=DeepSeekTaskHandler(invoke_model=invoke_model,
                               model_routes=model_routes,allow_pro=allow_pro)
    return run_due_once(queue,worker_id=worker_id,
                        model_handler=handler,now_utc=now_utc)

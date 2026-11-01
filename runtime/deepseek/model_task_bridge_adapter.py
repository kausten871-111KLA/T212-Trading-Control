"""Authenticated host-side adapter for model-scoped background tasks.

Staged contract only: a trusted WebUI backend or the EXISTING Contabo bridge
must verify caller identity and pass server-created auth context here. Never
accept a model-provided 'authenticated', 'principal', model ID or broker name
as proof of origin. This component does not register a new WebUI tool or
launch inference; deployment remains a separate supervised acceptance step.
"""
from __future__ import annotations
from .model_task_queue import MODEL_ID


class ModelTaskIngress:
    CREATE_KEYS=frozenset({"job_kind","instruction","scheduled_at_utc","dedupe_key",
                           "cost_tier","max_attempts"})
    CONTROL_KEYS=frozenset({"task_id"})

    def __init__(self, queue, verify_host):
        if not callable(verify_host):
            raise ValueError("Trusted host context verifier required")
        self.queue=queue
        self.verify_host=verify_host

    def execute(self, *, action, payload, host_context):
        if self.verify_host(host_context, MODEL_ID) is not True:
            raise PermissionError("Unauthenticated model task access")
        if not isinstance(payload,dict):
            raise ValueError("Task payload must be JSON object")
        if action=="create":
            if not set(payload).issubset(self.CREATE_KEYS):
                raise ValueError("Unexpected or spoofed fields in create")
            required={"job_kind","instruction","scheduled_at_utc","dedupe_key"}
            if not required.issubset(payload):
                raise ValueError("Missing required task fields")
            task_id,created=self.queue.enqueue(principal=host_context,
                                               **payload)
            return {"ok":True,"task_id":task_id,"created":created,
                    "model_id":MODEL_ID,"state":"pending" if created else "existing"}
        if action in ("status","cancel"):
            if set(payload)!=self.CONTROL_KEYS or not isinstance(payload["task_id"],str):
                raise ValueError("Explicit task_id required")
            if action=="status":
                result=self.queue.status(principal=host_context,task_id=payload["task_id"])
                if result is None:
                    return {"ok":False,"error":"not_found"}
                # Do not expose internals including any stored sensitive result text
                return {"ok":True,"task_id":result["task_id"],"model_id":result["model_id"],
                        "state":result["state"],"scheduled_at_utc":result["scheduled_at_utc"],
                        "attempts":result["attempts"]}
            changed=self.queue.cancel(principal=host_context,task_id=payload["task_id"])
            return {"ok":changed,"state":"cancelled" if changed else "unchanged"}
        raise ValueError("Unsupported background task action")

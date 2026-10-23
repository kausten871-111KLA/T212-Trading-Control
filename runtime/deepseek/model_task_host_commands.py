"""Model-task ingress from the EXISTING Contabo command-bridge HTTP server.

Only the server handler may pass a successful dedicated-token verification.
No principal, model ID, shell command, broker credential, or trade instruction
is taken from caller-provided authentication fields. The dedicated token must
be provisioned in the existing service and in one WebUI tool bound exclusively
to trading-operations--deepseek; a shared general bridge token is insufficient.
"""
from pathlib import Path

from .model_task_bridge_adapter import ModelTaskIngress
from .model_task_queue import ModelTaskQueue

DEFAULT_DB = Path("/home/katie/.local/state/deepseek-runtime/model_tasks.sqlite3")


def dispatch_model_task(payload, *, verified, db_path=DEFAULT_DB):
    if verified is not True:
        raise PermissionError("Dedicated host token verification required")
    if not isinstance(payload, dict) or set(payload) != {"action", "payload"}:
        raise ValueError("Expected exactly action and payload")
    context = object()  # minted after dedicated server-side token verification
    verify = lambda principal, model_id: (
        principal is context and model_id == "trading-operations--deepseek"
    )
    authorize = lambda principal, permission: (
        principal is context and permission in
        {"model_task:create", "model_task:status", "model_task:cancel"}
    )
    queue = ModelTaskQueue(db_path, authorize)
    try:
        ingress = ModelTaskIngress(queue, verify)
        return ingress.execute(action=payload["action"], payload=payload["payload"],
                               host_context=context)
    finally:
        queue.close()

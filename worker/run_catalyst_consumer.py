#!/usr/bin/env python3
"""Bounded catalyst-review consumer for deterministic T212 DEMO candidates.

The worker can call one configured OpenAI-compatible text endpoint. It validates
the response and annotates the queue only; it has no broker or order imports.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from openwebui.tools.catalyst_handoff_queue import CatalystHandoffQueue
from worker.session_gate import evaluate_session


STATE = Path(os.getenv("T212_SCANNER_STATE_DIR", "/var/lib/t212-scanner"))
QUEUE_PATH = Path(os.getenv("T212_CATALYST_QUEUE", str(STATE / "catalyst_handoff_queue.jsonl")))
STATUS_PATH = Path(os.getenv("T212_CATALYST_STATUS", str(STATE / "catalyst_consumer_status.json")))
REVIEW_LOG = Path(os.getenv("T212_CATALYST_REVIEW_LOG", str(STATE / "catalyst_reviews.jsonl")))
MAX_PER_RUN = min(5, max(1, int(os.getenv("T212_CATALYST_MAX_PER_RUN", "5"))))
MAX_PER_DAY = max(1, int(os.getenv("T212_CATALYST_MAX_PER_DAY", "20")))
MAX_ATTEMPTS = max(1, int(os.getenv("T212_CATALYST_MAX_ATTEMPTS", "3")))
LEASE_SECONDS = max(30, int(os.getenv("T212_CATALYST_LEASE_SECONDS", "120")))

ALLOWED_CATALYST_STATES = {"confirmed", "probable", "unknown"}
ALLOWED_DISPOSITIONS = {"qualify", "reject", "watch", "unknown"}
REQUIRED_FIELDS = {
    "symbol",
    "reason_tag",
    "catalyst_state",
    "headline",
    "source",
    "source_ts",
    "mechanism",
    "risk_flags",
    "disposition",
    "confidence",
}


class ReviewError(RuntimeError):
    pass


class Reviewer(Protocol):
    def review(self, candidate: dict[str, Any]) -> dict[str, Any]: ...


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(path)


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True, default=str) + "\n")
    path.chmod(0o600)


def validate_result(candidate: dict[str, Any], result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise ReviewError("review result must be a JSON object")
    missing = sorted(REQUIRED_FIELDS - set(result))
    if missing:
        raise ReviewError("review result missing fields: " + ", ".join(missing))
    expected_symbol = str(candidate.get("symbol") or "").upper()
    if str(result.get("symbol") or "").upper() != expected_symbol:
        raise ReviewError("review result symbol does not match candidate")
    if result.get("catalyst_state") not in ALLOWED_CATALYST_STATES:
        raise ReviewError("invalid catalyst_state")
    if result.get("disposition") not in ALLOWED_DISPOSITIONS:
        raise ReviewError("invalid disposition")
    if not isinstance(result.get("risk_flags"), list):
        raise ReviewError("risk_flags must be a list")
    try:
        confidence = float(result.get("confidence"))
    except (TypeError, ValueError) as exc:
        raise ReviewError("confidence must be numeric") from exc
    if not 0.0 <= confidence <= 1.0:
        raise ReviewError("confidence must be between 0 and 1")
    if result["catalyst_state"] in {"confirmed", "probable"} and not result.get("source"):
        raise ReviewError("confirmed/probable review requires a source")
    return {**result, "symbol": expected_symbol, "confidence": confidence}


class OpenAICompatibleReviewer:
    def __init__(self, *, url: str, token: str, model: str, timeout_seconds: int = 30):
        self.url = url
        self.token = token
        self.model = model
        self.timeout_seconds = max(1, min(60, int(timeout_seconds)))

    def review(self, candidate: dict[str, Any]) -> dict[str, Any]:
        system = (
            "You are a catalyst-verification analyst. Use only fresh, reliable sources available to you. "
            "Do not calculate sizing and do not recommend or place orders. Return exactly one JSON object "
            "with symbol, reason_tag, catalyst_state, headline, source, source_ts, mechanism, risk_flags, "
            "disposition and confidence. If evidence is insufficient, use catalyst_state=unknown."
        )
        payload = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps({"candidate": candidate}, default=str)},
            ],
        }
        request = urllib.request.Request(
            self.url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise ReviewError(f"catalyst provider request failed: {type(exc).__name__}") from exc
        try:
            content = body["choices"][0]["message"]["content"]
            return json.loads(content) if isinstance(content, str) else content
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ReviewError("catalyst provider returned invalid JSON response") from exc


def consume(
    queue: CatalystHandoffQueue,
    reviewer: Reviewer,
    *,
    max_per_run: int = MAX_PER_RUN,
    max_attempts: int = MAX_ATTEMPTS,
    lease_seconds: int = LEASE_SECONDS,
    now: datetime | None = None,
) -> dict[str, Any]:
    observed = now or datetime.now(timezone.utc)
    requested = min(5, max(1, int(max_per_run)))
    completed = []
    retried = []
    failed = []
    for event in queue.pending(requested, now=observed):
        claimed = queue.claim(event["id"], lease_seconds=lease_seconds, now=observed)
        if not claimed:
            continue
        try:
            result = validate_result(claimed["candidate"], reviewer.review(claimed["candidate"]))
            queue.acknowledge(claimed["id"], result=result, now=observed)
            completed.append({"event_id": claimed["id"], "result": result})
        except Exception as exc:
            updated = queue.retry(
                claimed["id"],
                error=f"{type(exc).__name__}: {exc}",
                max_attempts=max_attempts,
                now=observed,
            )
            target = failed if updated and updated.get("status") == "failed" else retried
            target.append({"event_id": claimed["id"], "error_type": type(exc).__name__})
    return {
        "processed": len(completed) + len(retried) + len(failed),
        "completed": completed,
        "retried": retried,
        "failed": failed,
        "queue": queue.stats(now=observed),
        "orders_submitted": 0,
        "live_trading_enabled": False,
        "order_mutation_enabled": False,
    }


def _write_status(payload: dict[str, Any]) -> None:
    atomic_json(STATUS_PATH, payload)
    print(json.dumps(payload, sort_keys=True))


def main() -> int:
    observed = datetime.now(timezone.utc)
    decision = evaluate_session(observed)
    base = {
        "observed_at": observed.isoformat(),
        "environment": "DEMO",
        "session_gate": decision.to_dict(),
        "orders_submitted": 0,
        "live_trading_enabled": False,
        "order_mutation_enabled": False,
    }
    if not decision.allowed:
        _write_status({**base, "ok": True, "skipped": True, "reason": decision.reason})
        return 0

    url = os.getenv("T212_CATALYST_REVIEW_URL", "").strip()
    token = os.getenv("T212_CATALYST_REVIEW_TOKEN", "").strip()
    model = os.getenv("WEBUI_MODEL_DEEP_REASONING", "").strip()
    queue = CatalystHandoffQueue(path=QUEUE_PATH, max_per_day=MAX_PER_DAY)
    if not (url and token and model):
        _write_status(
            {
                **base,
                "ok": False,
                "blocked": True,
                "reason": "catalyst reviewer endpoint, token or model is not configured",
                "queue": queue.stats(now=observed),
            }
        )
        return 0

    reviewer = OpenAICompatibleReviewer(
        url=url,
        token=token,
        model=model,
        timeout_seconds=int(os.getenv("T212_CATALYST_TIMEOUT_SECONDS", "30")),
    )
    result = consume(queue, reviewer, now=observed)
    for item in result["completed"]:
        append_jsonl(REVIEW_LOG, {"reviewed_at": observed.isoformat(), **item})
    _write_status({**base, "ok": not result["failed"], **result})
    return 0 if not result["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

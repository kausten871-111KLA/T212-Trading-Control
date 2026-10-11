#!/usr/bin/env python3
"""Bounded catalyst-review consumer for deterministic T212 DEMO candidates.

The worker can call one configured OpenAI-compatible text endpoint. It validates
the response and annotates the queue only; it has no broker or order imports.
"""

from __future__ import annotations

import json
import fcntl
import os
import sys
import uuid
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
    """Write a status receipt under a stable lock with crash-safe local durability.

    This is local POSIX filesystem durability, not a guarantee across network
    mounts, hardware failure or two independently managed deployment hosts.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False)
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, "a+") as lock:
        os.fchmod(lock.fileno(), 0o600)
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            if path.is_symlink():
                raise OSError("Status destination must not be a symlink")
            temporary = path.with_suffix(path.suffix + "." + uuid.uuid4().hex + ".tmp")
            try:
                fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as output:
                    output.write(encoded)
                    output.flush()
                    os.fsync(output.fileno())
                temporary.replace(path)
                directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            finally:
                temporary.unlink(missing_ok=True)
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    _persist_review(path, payload, idempotent=False)


def _persist_review(path: Path, payload: dict[str, Any], *, idempotent: bool) -> bool:
    """Atomic local-file projection; replay never duplicates a receipt."""
    encoded = json.dumps(payload, sort_keys=True, default=str, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "a") as lock:
        os.fchmod(lock.fileno(), 0o600)
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            if path.is_symlink():
                raise OSError("Review destination must not be a symlink")
            original = path.read_text(encoding="utf-8") if path.exists() else ""
            for line in original.splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)  # Corruption blocks writes; never discard evidence.
                if not isinstance(row, dict):
                    raise ValueError("Invalid review log record")
                if idempotent and (row.get("receipt_id") == payload["receipt_id"] or row.get("event_id") == payload["event_id"]):
                    fields = ("event_id", "scan_id", "scanner_event_id", "result")
                    if any(row.get(field) != payload.get(field) for field in fields):
                        raise ValueError("Conflicting review receipt; preserve evidence")
                    # Recovery may observe a replace whose directory fsync was
                    # interrupted. Make the existing receipt durable before ACK.
                    existing = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
                    try:
                        os.fchmod(existing, 0o600)
                        os.fsync(existing)
                    finally:
                        os.close(existing)
                    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        os.fsync(directory)
                    finally:
                        os.close(directory)
                    return False
            temporary = path.with_suffix(path.suffix + "." + uuid.uuid4().hex + ".tmp")
            try:
                descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    handle.write(original)
                    if original and not original.endswith("\n"):
                        handle.write("\n")
                    handle.write(encoded)
                    handle.flush()
                    os.fsync(handle.fileno())
                temporary.replace(path)
                directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            finally:
                temporary.unlink(missing_ok=True)
            return True
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def flush_review_outbox(queue: CatalystHandoffQueue, path: Path, *, limit: int = 100) -> dict[str, int]:
    delivered = replayed = 0
    for receipt in queue.pending_reviews(limit):
        inserted = _persist_review(path, receipt, idempotent=True)
        if not queue.mark_review_exported(receipt["event_id"], receipt["receipt_id"]):
            raise ReviewError("Review persisted but queue export receipt could not be marked")
        delivered += int(inserted)
        replayed += int(not inserted)
    return {"delivered": delivered, "replayed": replayed}


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
    clock=None,
) -> dict[str, Any]:
    clock = clock or (lambda: now if now is not None else datetime.now(timezone.utc))
    observed = clock()
    requested = min(5, max(1, int(max_per_run)))
    completed = []
    retried = []
    failed = []
    lease_lost = []
    for event in queue.pending(requested, now=observed):
        claimed = queue.claim(event["id"], lease_seconds=lease_seconds, max_attempts=max_attempts, now=clock())
        if not claimed:
            continue
        try:
            result = validate_result(claimed["candidate"], reviewer.review(claimed["candidate"]))
            acknowledged = queue.acknowledge(claimed["id"], result=result, lease_token=claimed["lease_token"], now=clock())
            if not acknowledged:
                lease_lost.append({"event_id": claimed["id"], "reason": "claim_expired_or_reassigned"})
                continue
            completed.append({"event_id": claimed["id"], "scan_id": claimed["candidate"].get("scan_id"), "scanner_event_id": claimed["candidate"].get("scanner_event_id"), "result": result})
        except Exception as exc:
            updated = queue.retry(
                claimed["id"],
                error=f"{type(exc).__name__}: {exc}",
                lease_token=claimed["lease_token"],
                max_attempts=max_attempts,
                now=clock(),
            )
            if not updated:
                lease_lost.append({"event_id": claimed["id"], "reason": "claim_expired_or_reassigned"})
                continue
            target = failed if updated and updated.get("status") == "failed" else retried
            target.append({"event_id": claimed["id"], "error_type": type(exc).__name__})
    return {
        "processed": len(completed) + len(retried) + len(failed) + len(lease_lost),
        "completed": completed,
        "retried": retried,
        "failed": failed,
        "lease_lost": lease_lost,
        "queue": queue.stats(now=clock()),
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
    queue = CatalystHandoffQueue(path=QUEUE_PATH, max_per_day=MAX_PER_DAY)
    # Local recovery does not require a market session, credentials or provider.
    base["review_recovery"] = flush_review_outbox(queue, REVIEW_LOG)
    if not decision.allowed:
        _write_status({**base, "ok": True, "skipped": True, "reason": decision.reason})
        return 0

    url = os.getenv("T212_CATALYST_REVIEW_URL", "").strip()
    token = os.getenv("T212_CATALYST_REVIEW_TOKEN", "").strip()
    model = os.getenv("WEBUI_MODEL_DEEP_REASONING", "").strip()
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
    result = consume(queue, reviewer)
    result["review_delivery"] = flush_review_outbox(queue, REVIEW_LOG)
    ok = not result["failed"] and not result["lease_lost"]
    _write_status({**base, "ok": ok, **result})
    return 0 if ok else 1


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recover-reviews-only", action="store_true",
                        help="Deliver persisted review receipts locally without calling a provider")
    parser.add_argument("--queue", type=Path, default=QUEUE_PATH)
    parser.add_argument("--review-log", type=Path, default=REVIEW_LOG)
    arguments = parser.parse_args()
    if arguments.recover_reviews_only:
        recovery = flush_review_outbox(CatalystHandoffQueue(arguments.queue), arguments.review_log)
        print(json.dumps({"ok": True, "recovery_only": True, "provider_calls": 0,
                          "orders_submitted": 0, **recovery}, sort_keys=True))
        raise SystemExit(0)
    if arguments.queue != QUEUE_PATH or arguments.review_log != REVIEW_LOG:
        parser.error("path overrides require --recover-reviews-only")
    raise SystemExit(main())


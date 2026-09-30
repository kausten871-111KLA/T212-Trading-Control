"""Durable JSONL automation ledger and deterministic health evaluation."""

from __future__ import annotations

import fcntl
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


WORKSPACES = {
    "t212-demo",
    "apps-plugins-bots",
    "you-heal-content",
    "books-publishing",
}
STATUSES = {"RUNNING", "SUCCEEDED", "FAILED", "BLOCKED", "CANCELLED"}
APPROVAL_STATES = {"NOT_REQUIRED", "PENDING", "APPROVED", "REJECTED"}
SECRET_MARKERS = ("sk-", "api_key=", "api-key=", "secret=", "password=", "bearer ")


class LedgerValidationError(ValueError):
    pass


def _parse_time(value: str | None, field: str) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise LedgerValidationError(f"{field} must be an ISO-8601 datetime") from exc
    if parsed.tzinfo is None:
        raise LedgerValidationError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _contains_secret(record: Mapping[str, Any]) -> bool:
    encoded = json.dumps(record, sort_keys=True).lower()
    return any(marker in encoded for marker in SECRET_MARKERS)


def validate_run(record: Mapping[str, Any]) -> None:
    required = {
        "run_id",
        "workspace",
        "workflow",
        "started_at",
        "status",
        "attempt",
        "input_refs",
        "output_refs",
        "evidence",
        "approvals",
        "next_action",
    }
    missing = required - set(record)
    if missing:
        raise LedgerValidationError(f"missing required fields: {sorted(missing)}")
    if record["workspace"] not in WORKSPACES:
        raise LedgerValidationError("unknown workspace")
    if record["status"] not in STATUSES:
        raise LedgerValidationError("unknown status")
    if not isinstance(record["attempt"], int) or not 1 <= record["attempt"] <= 10:
        raise LedgerValidationError("attempt must be an integer from 1 to 10")
    if not str(record["run_id"]).strip() or not str(record["workflow"]).strip():
        raise LedgerValidationError("run_id and workflow are required")
    started = _parse_time(record["started_at"], "started_at")
    ended = _parse_time(record.get("ended_at"), "ended_at")
    _parse_time(record.get("heartbeat_at"), "heartbeat_at")
    if ended is not None and ended < started:
        raise LedgerValidationError("ended_at cannot precede started_at")
    if record["status"] == "RUNNING" and ended is not None:
        raise LedgerValidationError("RUNNING record cannot have ended_at")
    if record["status"] != "RUNNING" and ended is None:
        raise LedgerValidationError("terminal record must have ended_at")

    for field in ("input_refs", "output_refs", "evidence", "approvals"):
        if not isinstance(record[field], list):
            raise LedgerValidationError(f"{field} must be a list")
    for approval in record["approvals"]:
        if approval.get("state") not in APPROVAL_STATES:
            raise LedgerValidationError("unknown approval state")

    if record["workspace"] == "t212-demo":
        safety = record.get("safety") or {}
        if safety.get("environment") != "DEMO":
            raise LedgerValidationError("T212 run must use DEMO")
        if safety.get("live_trading") is not False:
            raise LedgerValidationError("T212 LIVE trading must remain disabled")
        if safety.get("order_mutation") is not False:
            raise LedgerValidationError("overnight T212 run must deny order mutation")

    if _contains_secret(record):
        raise LedgerValidationError("record appears to contain a secret value")


def append_run(path: str | Path, record: Mapping[str, Any]) -> None:
    """Append one validated record with an advisory lock and private file mode."""

    validate_run(record)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
    fd = os.open(destination, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "a", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        raise


def read_runs(path: str | Path) -> list[dict[str, Any]]:
    destination = Path(path)
    if not destination.exists():
        return []
    records: list[dict[str, Any]] = []
    with destination.open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                validate_run(record)
            except (json.JSONDecodeError, LedgerValidationError) as exc:
                raise LedgerValidationError(f"invalid ledger line {number}: {exc}") from exc
            records.append(record)
    return records


def latest_by_workflow(records: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str], Mapping[str, Any]]:
    latest: dict[tuple[str, str], Mapping[str, Any]] = {}
    for record in records:
        validate_run(record)
        key = (record["workspace"], record["workflow"])
        current = latest.get(key)
        if current is None or _parse_time(record["started_at"], "started_at") > _parse_time(
            current["started_at"], "started_at"
        ):
            latest[key] = record
    return latest


def health_status(
    record: Mapping[str, Any],
    now: datetime | None = None,
    stale_after_seconds: int = 900,
) -> str:
    validate_run(record)
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    status = record["status"]
    if status == "RUNNING":
        heartbeat = _parse_time(record.get("heartbeat_at") or record["started_at"], "heartbeat_at")
        if (current - heartbeat).total_seconds() > stale_after_seconds:
            return "STALE"
        return "RUNNING"
    if status == "SUCCEEDED":
        return "HEALTHY"
    if status in {"FAILED", "BLOCKED"}:
        return "DEGRADED"
    return "STOPPED"

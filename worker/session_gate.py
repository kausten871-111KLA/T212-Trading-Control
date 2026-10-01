#!/usr/bin/env python3
"""Deterministic session gate and single-slot run guard for T212 discovery."""

from __future__ import annotations

import fcntl
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

SESSION_TIMEZONE = ZoneInfo("Europe/London")
SESSION_START = time(14, 20)
SESSION_END = time(21, 5)
SLOT_MINUTES = 5
MAX_ATTEMPTS_PER_SLOT = 2
STALE_RUNNING_SECONDS = 4 * 60


class RunGuardError(RuntimeError):
    """Base class for fail-closed run guard decisions."""


class RunAlreadyActive(RunGuardError):
    pass


class DuplicateSlot(RunGuardError):
    pass


class SlotAttemptsExhausted(RunGuardError):
    pass


@dataclass(frozen=True)
class SessionDecision:
    allowed: bool
    reason: str
    observed_at_utc: str
    observed_at_local: str
    timezone: str
    window: str
    slot_key: str | None

    def to_dict(self) -> dict:
        return asdict(self)


def evaluate_session(now: datetime | None = None) -> SessionDecision:
    """Return whether *now* belongs to an approved weekday five-minute slot.

    The last 21:05 slot remains valid through 21:09:59 so a bounded systemd
    misfire can still run it. The next 21:10 slot is rejected.
    """
    observed = now or datetime.now(timezone.utc)
    if observed.tzinfo is None:
        raise ValueError("session gate requires a timezone-aware datetime")

    observed_utc = observed.astimezone(timezone.utc)
    local = observed_utc.astimezone(SESSION_TIMEZONE)
    slot_minute = (local.minute // SLOT_MINUTES) * SLOT_MINUTES
    slot_local = local.replace(minute=slot_minute, second=0, microsecond=0)
    slot_clock = slot_local.time().replace(tzinfo=None)
    weekday = local.weekday() < 5
    in_window = SESSION_START <= slot_clock <= SESSION_END

    if not weekday:
        allowed = False
        reason = "weekend"
        slot_key = None
    elif not in_window:
        allowed = False
        reason = "outside_approved_window"
        slot_key = None
    else:
        allowed = True
        reason = "approved_session_slot"
        slot_key = slot_local.isoformat()

    return SessionDecision(
        allowed=allowed,
        reason=reason,
        observed_at_utc=observed_utc.isoformat(),
        observed_at_local=local.isoformat(),
        timezone="Europe/London",
        window="weekdays 14:20-21:05 Europe/London",
        slot_key=slot_key,
    )


class RunSlotGuard:
    """Non-blocking process lock plus persistent per-slot deduplication."""

    def __init__(
        self,
        *,
        lock_path: Path,
        state_path: Path,
        max_attempts: int = MAX_ATTEMPTS_PER_SLOT,
        stale_running_seconds: int = STALE_RUNNING_SECONDS,
    ) -> None:
        self.lock_path = Path(lock_path)
        self.state_path = Path(state_path)
        self.max_attempts = max_attempts
        self.stale_running_seconds = stale_running_seconds
        self._handle = None
        self._slot_key: str | None = None
        self._attempt = 0

    def acquire(self) -> None:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        self._handle = os.fdopen(descriptor, "a+")
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self._handle.close()
            self._handle = None
            raise RunAlreadyActive("another discovery process holds the run lock") from exc

    def _load(self) -> dict:
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _write(self, payload: dict) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(self.state_path)

    def start(self, slot_key: str, now: datetime | None = None) -> int:
        if self._handle is None:
            raise RunGuardError("run lock must be acquired before claiming a slot")
        observed = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        previous = self._load()
        attempt = 1

        if previous.get("slot_key") == slot_key:
            previous_status = previous.get("status")
            previous_attempt = int(previous.get("attempt") or 0)
            if previous_status == "COMPLETED":
                raise DuplicateSlot(f"slot {slot_key} already completed")
            if previous_attempt >= self.max_attempts:
                raise SlotAttemptsExhausted(f"slot {slot_key} exhausted bounded attempts")
            if previous_status == "RUNNING":
                try:
                    updated = datetime.fromisoformat(previous["updated_at"]).astimezone(timezone.utc)
                    age = (observed - updated).total_seconds()
                except (KeyError, TypeError, ValueError):
                    age = 0
                if age < self.stale_running_seconds:
                    raise RunAlreadyActive(f"slot {slot_key} is already marked RUNNING")
            attempt = previous_attempt + 1

        self._slot_key = slot_key
        self._attempt = attempt
        self._write(
            {
                "slot_key": slot_key,
                "status": "RUNNING",
                "attempt": attempt,
                "updated_at": observed.isoformat(),
            }
        )
        return attempt

    def complete(self, now: datetime | None = None) -> None:
        self._finish("COMPLETED", now)

    def fail(self, now: datetime | None = None) -> None:
        self._finish("FAILED", now)

    def _finish(self, status: str, now: datetime | None) -> None:
        if not self._slot_key:
            return
        observed = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        self._write(
            {
                "slot_key": self._slot_key,
                "status": status,
                "attempt": self._attempt,
                "updated_at": observed.isoformat(),
            }
        )

    def release(self) -> None:
        if self._handle is not None:
            try:
                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
            finally:
                self._handle.close()
                self._handle = None

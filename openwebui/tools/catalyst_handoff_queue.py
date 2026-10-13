"""Persistent catalyst handoff queue with deduplication, leases and retry control."""

from __future__ import annotations

import json
import os
import fcntl
import hmac
from functools import wraps
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


FINAL_STATES = {"done", "failed"}


def serialized_mutation(method):
    """Lock the complete read/check/rewrite transaction across local processes."""
    @wraps(method)
    def guarded(self, *args, **kwargs):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "a") as lock:
            os.fchmod(lock.fileno(), 0o600)
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                if self.path.is_symlink():
                    raise ValueError("Queue destination must not be a symlink")
                return method(self, *args, **kwargs)
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    return guarded


class CatalystHandoffQueue:
    def __init__(self, path="/app/backend/data/catalyst_handoff_queue.jsonl", max_per_day=20):
        self.path = Path(path)
        self.max_per_day = int(max_per_day)

    @staticmethod
    def _now(now: datetime | None = None) -> datetime:
        value = now or datetime.now(timezone.utc)
        if value.tzinfo is None:
            raise ValueError("queue timestamps must be timezone-aware")
        return value.astimezone(timezone.utc)

    def _today(self, now: datetime | None = None) -> str:
        return self._now(now).date().isoformat()

    def _read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        rows = []
        seen_ids = set()
        for number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Queue corruption at line {number}; preserve file for recovery") from exc
            if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"] or row.get("status") not in {"pending", "claimed", "done", "failed"}:
                raise ValueError(f"Invalid queue record at line {number}; preserve file for recovery")
            attempts = row.get("attempts", 0)
            if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 0:
                raise ValueError("Invalid queue attempt count; preserve file for recovery")
            if "review_outbox" in row:
                if (row.get("status") != "done" or "result" not in row
                        or row["review_outbox"] != self._review_receipt(row)):
                    raise ValueError("Review outbox does not match saved queue event; preserve evidence")
            if row["id"] in seen_ids:
                raise ValueError("Duplicate queue event ID; preserve file for recovery")
            seen_ids.add(row["id"])
            rows.append(row)
        return rows

    def _rewrite(self, rows: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + "." + uuid.uuid4().hex + ".tmp")
        encoded = "".join(json.dumps(row, sort_keys=True, allow_nan=False, default=str) + "\n" for row in rows)
        try:
            fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            tmp.replace(self.path)
            directory = os.open(self.path.parent, os.O_DIRECTORY | os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            tmp.unlink(missing_ok=True)

    def _dedup_key(self, candidate: dict[str, Any], now: datetime | None = None) -> str:
        symbol = str(candidate.get("symbol") or candidate.get("t212_ticker") or "").upper()
        tier = (candidate.get("tier_state") or {}).get("current_tier")
        return f"{self._today(now)}|{symbol}|{tier}"

    @serialized_mutation
    def enqueue(self, candidate: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
        observed = self._now(now)
        rows = self._read()
        today = self._today(observed)
        today_rows = [row for row in rows if row.get("session_date") == today]
        key = self._dedup_key(candidate, observed)
        for row in today_rows:
            if row.get("dedup_key") == key:
                return {"queued": False, "reason": "duplicate", "event": row}
        if len(today_rows) >= self.max_per_day:
            return {"queued": False, "reason": "daily_budget_reached", "daily_count": len(today_rows)}
        event = {
            "id": uuid.uuid4().hex,
            "queued_at": observed.isoformat(),
            "session_date": today,
            "status": "pending",
            "attempts": 0,
            "dedup_key": key,
            "candidate": candidate,
        }
        rows.append(event)
        self._rewrite(rows)
        return {"queued": True, "event": event}

    @staticmethod
    def _lease_expired(row: dict[str, Any], now: datetime) -> bool:
        lease = row.get("lease_expires_at")
        if not lease:
            return True
        try:
            expires = datetime.fromisoformat(str(lease))
            return expires.tzinfo is None or expires.astimezone(timezone.utc) <= now
        except (TypeError, ValueError):
            return True

    def pending(
        self,
        limit: int = 20,
        *,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        observed = self._now(now)
        claimable = [
            row
            for row in self._read()
            if row.get("status") == "pending"
            or (row.get("status") == "claimed" and self._lease_expired(row, observed))
        ]
        return claimable[: max(1, int(limit))]

    def completed(
        self,
        limit: int = 20,
        *,
        session_date: str | None = None,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        target_date = session_date or self._today(now)
        rows = [
            row
            for row in self._read()
            if row.get("status") == "done" and row.get("session_date") == target_date
        ]
        rows.sort(key=lambda row: str(row.get("completed_at") or row.get("queued_at") or ""), reverse=True)
        return rows[: max(1, int(limit))]

    @serialized_mutation
    def claim(
        self,
        event_id: str,
        *,
        lease_seconds: int = 120,
        max_attempts: int = 3,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        observed = self._now(now)
        rows = self._read()
        changed = None
        today = self._today(observed)
        for row in rows:
            if row.get("id") != event_id:
                continue
            if row.get("status") == "claimed" and not self._lease_expired(row, observed):
                break
            if row.get("status") not in {"pending", "claimed"}:
                break
            if int(row.get("attempts") or 0) >= max(1, int(max_attempts)):
                row.update(status="failed", completed_at=observed.isoformat(),
                           last_error="claim attempt budget exhausted")
                row.pop("lease_token", None)
                row.pop("lease_expires_at", None)
                self._rewrite(rows)
                return None
            if self._attempts_on(rows, today) >= self.max_per_day:
                return None
            if "review_attempts_by_date" not in row:
                previous_day = str(row.get("claimed_at") or "")[:10]
                row["review_attempts_by_date"] = {previous_day: int(row.get("attempts") or 0)} if previous_day else {}
            row["status"] = "claimed"
            row["attempts"] = int(row.get("attempts") or 0) + 1
            counts = row.setdefault("review_attempts_by_date", {})
            counts[today] = int(counts.get(today, 0)) + 1
            row["claimed_at"] = observed.isoformat()
            row["lease_token"] = uuid.uuid4().hex
            row["lease_expires_at"] = (observed + timedelta(seconds=max(1, int(lease_seconds)))).isoformat()
            changed = row
            break
        if changed:
            self._rewrite(rows)
        return changed

    @serialized_mutation
    def acknowledge(
        self,
        event_id: str,
        outcome: str = "done",
        result: dict[str, Any] | None = None,
        *,
        lease_token: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        if outcome not in FINAL_STATES:
            raise ValueError("queue acknowledgement outcome must be done or failed")
        observed = self._now(now)
        rows = self._read()
        changed = None
        for row in rows:
            if row.get("id") == event_id and self._owns_claim(row, lease_token, observed):
                row["status"] = outcome
                row["completed_at"] = observed.isoformat()
                if result is not None:
                    row["result"] = result
                row.pop("lease_expires_at", None)
                row.pop("lease_token", None)
                if outcome == "done" and result is not None:
                    # Result and delivery intent commit in the same atomic rewrite.
                    row["review_outbox"] = self._review_receipt(row)
                changed = row
                break
        if changed:
            self._rewrite(rows)
        return changed

    @serialized_mutation
    def retry(
        self,
        event_id: str,
        *,
        error: str,
        lease_token: str | None = None,
        max_attempts: int = 3,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        observed = self._now(now)
        rows = self._read()
        changed = None
        for row in rows:
            if row.get("id") != event_id or not self._owns_claim(row, lease_token, observed):
                continue
            row["last_error"] = str(error)[:500]
            row["last_error_at"] = observed.isoformat()
            row.pop("lease_expires_at", None)
            row.pop("lease_token", None)
            if int(row.get("attempts") or 0) >= max(1, int(max_attempts)):
                row["status"] = "failed"
                row["completed_at"] = observed.isoformat()
            else:
                row["status"] = "pending"
            changed = row
            break
        if changed:
            self._rewrite(rows)
        return changed

    @classmethod
    def _owns_claim(cls, row, lease_token, observed):
        stored = row.get("lease_token")
        return (row.get("status") == "claimed" and isinstance(lease_token, str)
                and bool(lease_token) and isinstance(stored, str)
                and hmac.compare_digest(stored, lease_token)
                and not cls._lease_expired(row, observed))

    @staticmethod
    def _attempts_on(rows, day):
        total = 0
        for row in rows:
            counts = row.get("review_attempts_by_date")
            if counts is not None:
                if not isinstance(counts, dict) or any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in counts.values()):
                    raise ValueError("Invalid review-attempt accounting; preserve queue")
                total += counts.get(day, 0)
            elif str(row.get("claimed_at") or "")[:10] == day:
                # Existing records have only the latest claim timestamp. Count all
                # their attempts that day rather than invent spare provider budget.
                total += int(row.get("attempts") or 0)
        return total

    @staticmethod
    def _review_receipt(row):
        candidate = row.get("candidate") or {}
        return {"receipt_id": "catalyst-review:" + row["id"], "event_id": row["id"],
                "scan_id": candidate.get("scan_id"),
                "scanner_event_id": candidate.get("scanner_event_id"),
                "reviewed_at": row.get("completed_at"), "result": row["result"]}

    def pending_reviews(self, limit: int = 100):
        """Recover exports, including pre-outbox done records with saved results."""
        return [row.get("review_outbox") or self._review_receipt(row)
                for row in self._read()
                if row.get("status") == "done" and "result" in row
                and not row.get("review_exported_at")][:max(0, int(limit))]

    @serialized_mutation
    def mark_review_exported(self, event_id, receipt_id, *, now=None):
        rows = self._read()
        for row in rows:
            if row["id"] != event_id or row.get("status") != "done" or "result" not in row:
                continue
            expected = row.get("review_outbox") or self._review_receipt(row)
            if expected["receipt_id"] != receipt_id:
                raise ValueError("Review export receipt does not match queue event")
            if not row.get("review_exported_at"):
                row["review_exported_at"] = self._now(now).isoformat()
                self._rewrite(rows)
            return True
        return False

    def stats(self, now: datetime | None = None) -> dict[str, Any]:
        today = self._today(now)
        rows = self._read()
        today_rows = [row for row in rows if row.get("session_date") == today]
        return {
            "session_date": today,
            "daily_budget": self.max_per_day,
            "review_attempts_today": self._attempts_on(rows, today),
            "review_attempt_budget": self.max_per_day,
            "today_count": len(today_rows),
            "pending": sum(row.get("status") == "pending" for row in today_rows),
            "claimed": sum(row.get("status") == "claimed" for row in today_rows),
            "done": sum(row.get("status") == "done" for row in today_rows),
            "failed": sum(row.get("status") == "failed" for row in today_rows),
        }



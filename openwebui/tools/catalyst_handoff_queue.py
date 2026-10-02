"""Persistent catalyst handoff queue with deduplication, leases and retry control."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


FINAL_STATES = {"done", "failed"}


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
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except (TypeError, ValueError):
                continue
            if isinstance(row, dict):
                rows.append(row)
        return rows

    def _rewrite(self, rows: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            "".join(json.dumps(row, default=str, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )
        tmp.chmod(0o600)
        tmp.replace(self.path)

    def _dedup_key(self, candidate: dict[str, Any], now: datetime | None = None) -> str:
        symbol = str(candidate.get("symbol") or candidate.get("t212_ticker") or "").upper()
        tier = (candidate.get("tier_state") or {}).get("current_tier")
        return f"{self._today(now)}|{symbol}|{tier}"

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
            return datetime.fromisoformat(str(lease)).astimezone(timezone.utc) <= now
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

    def claim(
        self,
        event_id: str,
        *,
        lease_seconds: int = 120,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        observed = self._now(now)
        rows = self._read()
        changed = None
        for row in rows:
            if row.get("id") != event_id:
                continue
            if row.get("status") == "claimed" and not self._lease_expired(row, observed):
                break
            if row.get("status") not in {"pending", "claimed"}:
                break
            row["status"] = "claimed"
            row["attempts"] = int(row.get("attempts") or 0) + 1
            row["claimed_at"] = observed.isoformat()
            row["lease_expires_at"] = (observed + timedelta(seconds=max(1, int(lease_seconds)))).isoformat()
            changed = row
            break
        if changed:
            self._rewrite(rows)
        return changed

    def acknowledge(
        self,
        event_id: str,
        outcome: str = "done",
        result: dict[str, Any] | None = None,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        if outcome not in FINAL_STATES:
            raise ValueError("queue acknowledgement outcome must be done or failed")
        observed = self._now(now)
        rows = self._read()
        changed = None
        for row in rows:
            if row.get("id") == event_id and row.get("status") == "claimed":
                row["status"] = outcome
                row["completed_at"] = observed.isoformat()
                if result is not None:
                    row["result"] = result
                row.pop("lease_expires_at", None)
                changed = row
                break
        if changed:
            self._rewrite(rows)
        return changed

    def retry(
        self,
        event_id: str,
        *,
        error: str,
        max_attempts: int = 3,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        observed = self._now(now)
        rows = self._read()
        changed = None
        for row in rows:
            if row.get("id") != event_id or row.get("status") != "claimed":
                continue
            row["last_error"] = str(error)[:500]
            row["last_error_at"] = observed.isoformat()
            row.pop("lease_expires_at", None)
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

    def stats(self, now: datetime | None = None) -> dict[str, Any]:
        today = self._today(now)
        today_rows = [row for row in self._read() if row.get("session_date") == today]
        return {
            "session_date": today,
            "daily_budget": self.max_per_day,
            "today_count": len(today_rows),
            "pending": sum(row.get("status") == "pending" for row in today_rows),
            "claimed": sum(row.get("status") == "claimed" for row in today_rows),
            "done": sum(row.get("status") == "done" for row in today_rows),
            "failed": sum(row.get("status") == "failed" for row in today_rows),
        }

"""Durable cursor and acknowledgement ledger for scanner-to-DeepSeek batches.

Isolated foundation: no polling loop, model API, service, or scanner DB writes.
The runtime must inject an authenticated DeepSeek Light handler and persist
INVESTIGATOR plus DECISION receipts. Daily inference budget defaults to zero.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping

DEFAULT_DB = Path("/home/katie/.local/state/deepseek-runtime/scanner_consumer.sqlite3")
DEFAULT_CONSUMER = "market-scanner-investigator"
DEFAULT_POLL_SECONDS = 900
DEFAULT_BATCH_SIZE = 12
DEFAULT_MAX_CALLS_PER_UTC_DAY = 0

SCHEMA = """
CREATE TABLE IF NOT EXISTS consumer_state (
  consumer_name TEXT PRIMARY KEY,
  cursor_id INTEGER NOT NULL DEFAULT -1,
  last_poll_utc TEXT,
  updated_at_utc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS consumer_batch (
  batch_id TEXT PRIMARY KEY,
  consumer_name TEXT NOT NULL,
  cursor_before INTEGER NOT NULL,
  cursor_after INTEGER NOT NULL,
  candidate_ids_json TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  state TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 3,
  next_attempt_utc TEXT,
  lease_owner TEXT,
  lease_expires_utc TEXT,
  receipt_id TEXT,
  last_error_type TEXT,
  created_at_utc TEXT NOT NULL,
  acknowledged_at_utc TEXT
);
CREATE INDEX IF NOT EXISTS idx_consumer_batch_due
  ON consumer_batch(consumer_name, state, next_attempt_utc, created_at_utc);
CREATE TABLE IF NOT EXISTS model_call_budget (
  utc_date TEXT PRIMARY KEY,
  calls_reserved INTEGER NOT NULL DEFAULT 0
);
"""

class ConsumerError(ValueError):
    """Invalid page, lease, or acknowledgement contract."""

def _utc(value: datetime | str | None = None) -> datetime:
    if value is None:
        value = datetime.now(timezone.utc)
    elif isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ConsumerError("timezone-aware timestamp required")
    return value.astimezone(timezone.utc)

def _stamp(value: datetime | str | None = None) -> str:
    return _utc(value).isoformat(timespec="seconds").replace("+00:00", "Z")

def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)

class ScannerCandidateConsumer:
    """Persist pages, retries, model-call reservations, and explicit ACKs.

    stage_page accepts the existing scanner_candidates response. It never
    advances the cursor. acknowledge advances only after every candidate ID
    and both investigation and decision receipts are explicitly confirmed.
    Retrying after a crash is at-least-once; batch_id stays stable.
    """

    def __init__(
        self,
        db_path: str | Path = DEFAULT_DB,
        *,
        consumer_name: str = DEFAULT_CONSUMER,
        poll_seconds: int = DEFAULT_POLL_SECONDS,
        batch_size: int = DEFAULT_BATCH_SIZE,
        max_attempts: int = 3,
    ):
        if not consumer_name or len(consumer_name) > 100:
            raise ConsumerError("invalid consumer_name")
        if type(poll_seconds) is not int or not 60 <= poll_seconds <= 3600:
            raise ConsumerError("poll_seconds must be 60..3600")
        if type(batch_size) is not int or not 1 <= batch_size <= 12:
            raise ConsumerError("batch_size must be 1..12")
        if type(max_attempts) is not int or not 1 <= max_attempts <= 10:
            raise ConsumerError("max_attempts must be 1..10")
        self.path = Path(db_path)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.consumer_name = consumer_name
        self.poll_seconds = poll_seconds
        self.batch_size = batch_size
        self.max_attempts = max_attempts
        self.db = sqlite3.connect(str(self.path), isolation_level=None, timeout=15)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA busy_timeout=15000")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        now = _stamp()
        self.db.execute(
            "INSERT OR IGNORE INTO consumer_state(consumer_name,cursor_id,updated_at_utc) "
            "VALUES(?, -1, ?)",
            (self.consumer_name, now),
        )

    def close(self) -> None:
        self.db.close()

    def cursor(self) -> int:
        row = self.db.execute(
            "SELECT cursor_id FROM consumer_state WHERE consumer_name=?",
            (self.consumer_name,),
        ).fetchone()
        return int(row["cursor_id"])

    def poll_due(self, *, now_utc: datetime | str | None = None) -> bool:
        now = _utc(now_utc)
        row = self.db.execute(
            "SELECT last_poll_utc FROM consumer_state WHERE consumer_name=?",
            (self.consumer_name,),
        ).fetchone()
        return not row["last_poll_utc"] or (
            now - _utc(row["last_poll_utc"])
        ).total_seconds() >= self.poll_seconds

    def stage_page(
        self,
        page: Mapping[str, Any],
        *,
        requested_cursor: int,
        now_utc: datetime | str | None = None,
    ) -> str | None:
        """Persist one bounded scanner page without advancing its cursor.

        The initial -1 cursor uses the bridge's newest-page bootstrap. Older
        scanner history remains available but is not replayed by this consumer.
        """
        now = _stamp(now_utc)
        if page.get("ok") is not True or page.get("command") != "scanner_candidates":
            raise ConsumerError("scanner_candidates page was not successful")
        if type(requested_cursor) is not int or requested_cursor < -1:
            raise ConsumerError("invalid requested_cursor")
        if page.get("cursor_requested") != requested_cursor:
            raise ConsumerError("response cursor does not match request")
        records = page.get("records")
        if not isinstance(records, list) or len(records) > self.batch_size:
            raise ConsumerError("invalid or oversized records")
        if self.cursor() != requested_cursor:
            raise ConsumerError("stale cursor; reload persisted cursor")
        if not records:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                self.db.execute(
                    "UPDATE consumer_state SET last_poll_utc=?,updated_at_utc=? "
                    "WHERE consumer_name=?",
                    (now, now, self.consumer_name),
                )
                self.db.execute("COMMIT")
            except Exception:
                if self.db.in_transaction:
                    self.db.execute("ROLLBACK")
                raise
            return None
        ids = []
        for record in records:
            if not isinstance(record, dict) or type(record.get("id")) is not int or record["id"] < 1:
                raise ConsumerError("candidate requires a positive integer id")
            ids.append(record["id"])
        if ids != sorted(set(ids)):
            raise ConsumerError("candidate IDs must be unique and ascending")
        next_cursor, max_id = page.get("next_cursor"), page.get("max_id_at_read")
        if type(next_cursor) is not int or next_cursor != ids[-1]:
            raise ConsumerError("next_cursor must equal the last returned candidate ID")
        if type(max_id) is not int or max_id < next_cursor:
            raise ConsumerError("invalid max_id_at_read")
        if requested_cursor >= 0 and ids[0] <= requested_cursor:
            raise ConsumerError("incremental page contains an acknowledged ID")

        identity = {"consumer": self.consumer_name, "before": requested_cursor,
                    "after": next_cursor, "ids": ids}
        batch_id = hashlib.sha256(_canonical(identity).encode("utf-8")).hexdigest()
        payload = {"batch_id": batch_id, "cursor_before": requested_cursor,
                   "cursor_after": next_cursor, "max_id_at_read": max_id,
                   "candidate_ids": ids, "records": records}
        self.db.execute("BEGIN IMMEDIATE")
        try:
            old = self.db.execute(
                "SELECT batch_id FROM consumer_batch WHERE batch_id=?", (batch_id,)
            ).fetchone()
            if old:
                self.db.execute("COMMIT")
                return batch_id
            self.db.execute(
                "INSERT INTO consumer_batch(batch_id,consumer_name,cursor_before,"
                "cursor_after,candidate_ids_json,payload_json,state,max_attempts,created_at_utc) "
                "VALUES(?,?,?,?,?,?,'pending',?,?)",
                (batch_id, self.consumer_name, requested_cursor, next_cursor,
                 _canonical(ids), _canonical(payload), self.max_attempts, now),
            )
            self.db.execute(
                "UPDATE consumer_state SET last_poll_utc=?,updated_at_utc=? "
                "WHERE consumer_name=?",
                (now, now, self.consumer_name),
            )
            self.db.execute("COMMIT")
        except Exception:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise
        return batch_id

    def pending_batch(self, *, now_utc: datetime | str | None = None) -> dict[str, Any] | None:
        now = _stamp(now_utc)
        row = self.db.execute(
            "SELECT * FROM consumer_batch WHERE consumer_name=? AND "
            "(state='pending' OR (state='retry_wait' AND next_attempt_utc<=?) "
            "OR (state='in_flight' AND lease_expires_utc<=?)) "
            "ORDER BY created_at_utc,batch_id LIMIT 1",
            (self.consumer_name, now, now),
        ).fetchone()
        return dict(row) if row else None

    def claim_for_model(
        self,
        *,
        worker_id: str,
        max_calls_per_utc_day: int = DEFAULT_MAX_CALLS_PER_UTC_DAY,
        lease_seconds: int = 180,
        now_utc: datetime | str | None = None,
    ) -> dict[str, Any] | None:
        """Claim one batch and reserve one call; a zero budget disables inference."""
        if not worker_id or type(lease_seconds) is not int or not 30 <= lease_seconds <= 3600:
            raise ConsumerError("invalid worker lease")
        if type(max_calls_per_utc_day) is not int or max_calls_per_utc_day < 0:
            raise ConsumerError("invalid daily model-call budget")
        if max_calls_per_utc_day == 0:
            return None
        now = _utc(now_utc)
        now_s, day = _stamp(now), now.date().isoformat()
        expires = _stamp(now + timedelta(seconds=lease_seconds))
        try:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute(
                "SELECT * FROM consumer_batch WHERE consumer_name=? AND "
                "(state='pending' OR (state='retry_wait' AND next_attempt_utc<=?) "
                "OR (state='in_flight' AND lease_expires_utc<=?)) "
                "ORDER BY created_at_utc,batch_id LIMIT 1",
                (self.consumer_name, now_s, now_s),
            ).fetchone()
            if row is None or row["attempts"] >= row["max_attempts"]:
                self.db.execute("COMMIT")
                return None
            self.db.execute(
                "INSERT OR IGNORE INTO model_call_budget(utc_date,calls_reserved) VALUES(?,0)",
                (day,),
            )
            used = self.db.execute(
                "SELECT calls_reserved FROM model_call_budget WHERE utc_date=?", (day,)
            ).fetchone()[0]
            if used >= max_calls_per_utc_day:
                self.db.execute("COMMIT")
                return None
            self.db.execute(
                "UPDATE model_call_budget SET calls_reserved=calls_reserved+1 WHERE utc_date=?",
                (day,),
            )
            self.db.execute(
                "UPDATE consumer_batch SET state='in_flight',attempts=attempts+1,"
                "lease_owner=?,lease_expires_utc=?,next_attempt_utc=NULL WHERE batch_id=?",
                (worker_id, expires, row["batch_id"]),
            )
            result = dict(self.db.execute(
                "SELECT * FROM consumer_batch WHERE batch_id=?", (row["batch_id"],)
            ).fetchone())
            self.db.execute("COMMIT")
            result["payload"] = json.loads(result["payload_json"])
            return result
        except Exception:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise

    def acknowledge(
        self,
        *,
        batch_id: str,
        worker_id: str,
        receipt_id: str,
        candidate_ids: list[int],
        investigator_ack: bool,
        decision_ack: bool,
        now_utc: datetime | str | None = None,
    ) -> int:
        if not receipt_id or investigator_ack is not True or decision_ack is not True:
            raise ConsumerError("both INVESTIGATOR and DECISION receipts are required")
        now = _stamp(now_utc)
        try:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute(
                "SELECT * FROM consumer_batch WHERE batch_id=? AND consumer_name=?",
                (batch_id, self.consumer_name),
            ).fetchone()
            if row is None or row["state"] != "in_flight" or row["lease_owner"] != worker_id:
                raise ConsumerError("batch is not owned by this worker")
            if _utc(row["lease_expires_utc"]) <= _utc(now):
                raise ConsumerError("batch lease expired")
            expected = json.loads(row["candidate_ids_json"])
            if candidate_ids != expected:
                raise ConsumerError("ack must cover every candidate in the batch")
            state = self.db.execute(
                "SELECT cursor_id FROM consumer_state WHERE consumer_name=?",
                (self.consumer_name,),
            ).fetchone()
            if int(state["cursor_id"]) != int(row["cursor_before"]):
                raise ConsumerError("cursor changed while batch was in flight")
            self.db.execute(
                "UPDATE consumer_batch SET state='acknowledged',receipt_id=?,"
                "lease_owner=NULL,lease_expires_utc=NULL,acknowledged_at_utc=? "
                "WHERE batch_id=?",
                (receipt_id, now, batch_id),
            )
            self.db.execute(
                "UPDATE consumer_state SET cursor_id=?,updated_at_utc=? WHERE consumer_name=?",
                (row["cursor_after"], now, self.consumer_name),
            )
            self.db.execute("COMMIT")
            return int(row["cursor_after"])
        except Exception:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise

    def fail(
        self,
        *,
        batch_id: str,
        worker_id: str,
        error_type: str,
        now_utc: datetime | str | None = None,
    ) -> str:
        now = _utc(now_utc)
        try:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute(
                "SELECT attempts,max_attempts FROM consumer_batch WHERE batch_id=? "
                "AND consumer_name=? AND state='in_flight' AND lease_owner=?",
                (batch_id, self.consumer_name, worker_id),
            ).fetchone()
            if row is None:
                raise ConsumerError("batch lease not owned")
            terminal = int(row["attempts"]) >= int(row["max_attempts"])
            wait = min(3600, 30 * (2 ** max(0, int(row["attempts"]) - 1)))
            next_try = _stamp(now + timedelta(seconds=wait))
            state = "failed" if terminal else "retry_wait"
            self.db.execute(
                "UPDATE consumer_batch SET state=?,next_attempt_utc=?,last_error_type=?,"
                "lease_owner=NULL,lease_expires_utc=NULL WHERE batch_id=?",
                (state, next_try, error_type[:80], batch_id),
            )
            self.db.execute("COMMIT")
            return state
        except Exception:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise

    def status(self) -> dict[str, Any]:
        state = self.db.execute(
            "SELECT cursor_id,last_poll_utc FROM consumer_state WHERE consumer_name=?",
            (self.consumer_name,),
        ).fetchone()
        counts = dict(self.db.execute(
            "SELECT state,count(*) FROM consumer_batch WHERE consumer_name=? GROUP BY state",
            (self.consumer_name,),
        ).fetchall())
        return {"consumer": self.consumer_name, "cursor_id": int(state["cursor_id"]),
                "last_poll_utc": state["last_poll_utc"], "batch_counts": counts}

"""Chat-independent DeepSeek task ledger, designed for the EXISTING controller host.

Staged component: no daemon, scheduler, model call or broker gateway is installed here.
An authenticated WebUI/host adapter must expose these operations and invoke the
existing durable worker before tasks actually run outside a chat. A user-supplied
principal or model-generated assertion is never proof of authentication.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import sqlite3
import uuid

MODEL_ID = "trading-operations--deepseek"
JOB_KINDS = frozenset({"research", "analysis", "engineering", "review"})
TIERS = frozenset({"light", "pro"})
SCHEMA = """
CREATE TABLE IF NOT EXISTS model_background_task (
 task_id TEXT PRIMARY KEY,
 dedupe_key TEXT NOT NULL UNIQUE,
 model_id TEXT NOT NULL,
 job_kind TEXT NOT NULL,
 instruction TEXT NOT NULL,
 cost_tier TEXT NOT NULL,
 scheduled_at_utc TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'pending',
 attempts INTEGER NOT NULL DEFAULT 0,
 max_attempts INTEGER NOT NULL DEFAULT 3,
 lease_owner TEXT,
 lease_until_utc TEXT,
 result_json TEXT,
 error TEXT,
 created_at_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_model_background_due
 ON model_background_task(state,scheduled_at_utc);
"""


def utc(value):
    if isinstance(value, datetime):
        stamp = value
    elif isinstance(value, str):
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError("Timezone-aware datetime required")
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("Timezone-aware datetime required")
    return stamp.astimezone(timezone.utc).isoformat(timespec="seconds")


def shift(value, seconds):
    return utc(datetime.fromisoformat(utc(value)) + timedelta(seconds=seconds))


class ModelTaskQueue:
    """Single persistent task ledger; does not replace existing market schedules."""

    def __init__(self, path, authorizer):
        if not callable(authorizer):
            raise ValueError("Trusted host authorizer required")
        self.authorizer = authorizer
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.path), isolation_level=None, timeout=15)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA busy_timeout=15000")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)

    def close(self):
        self.db.close()

    def _auth(self, principal, permission):
        if self.authorizer(principal, permission) is not True:
            raise PermissionError("Host authentication required")

    def enqueue(self, *, principal, job_kind, instruction, scheduled_at_utc,
                dedupe_key, cost_tier="light", max_attempts=3, now_utc=None):
        """Idempotent authenticated request, scoped to the existing model ID.

        Research/analysis/engineering/review tasks never directly place trades.
        The existing autonomous DEMO broker gateway remains the only executor.
        """
        self._auth(principal, "model_task:create")
        if job_kind not in JOB_KINDS or cost_tier not in TIERS:
            raise ValueError("Unsupported task kind or cost tier")
        if not isinstance(instruction, str) or not 1 <= len(instruction.strip()) <= 12000:
            raise ValueError("Task instruction must be 1..12000 characters")
        if not isinstance(dedupe_key, str) or not 1 <= len(dedupe_key) <= 180:
            raise ValueError("Nonempty stable dedupe key required")
        if type(max_attempts) is not int or not 1 <= max_attempts <= 10:
            raise ValueError("Invalid retry budget")
        when = utc(scheduled_at_utc)
        now = utc(now_utc or datetime.now(timezone.utc))
        normalized = instruction.strip()
        db = self.db
        try:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM model_background_task WHERE dedupe_key=?",
                             (dedupe_key,)).fetchone()
            if old:
                fields = (old["job_kind"], old["instruction"], old["cost_tier"],
                          old["scheduled_at_utc"], old["max_attempts"])
                if fields != (job_kind, normalized, cost_tier, when, max_attempts):
                    raise ValueError("Conflicting replay for dedupe key")
                db.execute("COMMIT")
                return old["task_id"], False
            task_id = uuid.uuid4().hex
            db.execute(
                "INSERT INTO model_background_task "
                "(task_id,dedupe_key,model_id,job_kind,instruction,cost_tier,"
                "scheduled_at_utc,max_attempts,created_at_utc) VALUES(?,?,?,?,?,?,?,?,?)",
                (task_id,dedupe_key,MODEL_ID,job_kind,normalized,cost_tier,when,
                 max_attempts,now))
            db.execute("COMMIT")
            return task_id, True
        except Exception:
            db.execute("ROLLBACK")
            raise

    def claim(self, *, worker_id, now_utc=None, lease_seconds=120, limit=3):
        """Atomically claim due work; stale workers cannot commit results."""
        if not isinstance(worker_id,str) or not worker_id.strip():
            raise ValueError("Worker ID required")
        if type(lease_seconds) is not int or not 10 <= lease_seconds <= 3600:
            raise ValueError("Invalid lease")
        if type(limit) is not int or not 1 <= limit <= 25:
            raise ValueError("Invalid batch")
        now = utc(now_utc or datetime.now(timezone.utc))
        expires = shift(now,lease_seconds)
        db = self.db
        try:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "UPDATE model_background_task SET state='failed',error='retry_exhausted',"
                "lease_owner=NULL,lease_until_utc=NULL WHERE state='running' "
                "AND lease_until_utc<=? AND attempts>=max_attempts", (now,))
            rows = db.execute(
                "SELECT task_id FROM model_background_task "
                "WHERE (state='pending' AND scheduled_at_utc<=?) OR "
                "(state='running' AND lease_until_utc<=? AND attempts<max_attempts) "
                "ORDER BY scheduled_at_utc, task_id LIMIT ?", (now,now,limit)).fetchall()
            ids = [x["task_id"] for x in rows]
            for task_id in ids:
                db.execute("UPDATE model_background_task SET state='running',"
                           "lease_owner=?,lease_until_utc=?,attempts=attempts+1 "
                           "WHERE task_id=?", (worker_id,expires,task_id))
            result = [dict(db.execute("SELECT * FROM model_background_task WHERE task_id=?",
                                      (tid,)).fetchone()) for tid in ids]
            db.execute("COMMIT")
            return result
        except Exception:
            db.execute("ROLLBACK")
            raise

    def finish(self, *, task_id, worker_id, result, now_utc=None):
        """Complete only if the worker still owns an unexpired lease."""
        now = utc(now_utc or datetime.now(timezone.utc))
        output = json.dumps(result,sort_keys=True,separators=(",",":"),allow_nan=False)
        if len(output)>30000:
            raise ValueError("Result too large")
        db = self.db
        try:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute(
                "UPDATE model_background_task SET state='completed',result_json=?,"
                "lease_owner=NULL,lease_until_utc=NULL WHERE task_id=? AND "
                "state='running' AND lease_owner=? AND lease_until_utc>?",
                (output,task_id,worker_id,now)).rowcount
            db.execute("COMMIT")
            return changed == 1
        except Exception:
            db.execute("ROLLBACK")
            raise

    def fail(self, *, task_id, worker_id, error, now_utc=None, retry_seconds=60):
        """Retry only within the recorded attempt budget."""
        if type(retry_seconds) is not int or not 1<=retry_seconds<=86400:
            raise ValueError("Invalid retry delay")
        now=utc(now_utc or datetime.now(timezone.utc))
        db=self.db
        try:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute(
                "SELECT attempts,max_attempts FROM model_background_task WHERE "
                "task_id=? AND state='running' AND lease_owner=? AND lease_until_utc>?",
                (task_id,worker_id,now)).fetchone()
            if not row:
                db.execute("COMMIT")
                return False
            retry=row["attempts"] < row["max_attempts"]
            db.execute(
                "UPDATE model_background_task SET state=?, scheduled_at_utc=?,"
                "error=?,lease_owner=NULL,lease_until_utc=NULL WHERE task_id=?",
                ("pending" if retry else "failed", shift(now,retry_seconds) if retry else now,
                 str(error)[:350],task_id))
            db.execute("COMMIT")
            return True
        except Exception:
            db.execute("ROLLBACK")
            raise

    def cancel(self, *, principal, task_id):
        self._auth(principal, "model_task:cancel")
        return self.db.execute(
            "UPDATE model_background_task SET state='cancelled',"
            "lease_owner=NULL,lease_until_utc=NULL WHERE task_id=? "
            "AND state IN ('pending','running')", (task_id,)).rowcount == 1

    def status(self, *, principal, task_id):
        self._auth(principal, "model_task:status")
        row=self.db.execute("SELECT * FROM model_background_task WHERE task_id=?",
                            (task_id,)).fetchone()
        return dict(row) if row else None


def run_due_once(queue, *, worker_id, model_handler, now_utc=None):
    """Adapter for the EXISTING supervisor; handler supplied by trusted host.

    This function does not instantiate another scheduler or access a broker.
    Actual DeepSeek inference remains the host adapter's responsibility.
    """
    if not callable(model_handler):
        raise ValueError("Trusted model handler required")
    counts={"completed":0,"retry":0,"failed":0}
    for task in queue.claim(worker_id=worker_id,now_utc=now_utc):
        try:
            result=model_handler(task)
            if queue.finish(task_id=task["task_id"],worker_id=worker_id,result=result,
                            now_utc=now_utc):
                counts["completed"]+=1
        except Exception as exc:
            if queue.fail(task_id=task["task_id"],worker_id=worker_id,error=type(exc).__name__,
                          now_utc=now_utc):
                counts["retry"]+=1
    return counts

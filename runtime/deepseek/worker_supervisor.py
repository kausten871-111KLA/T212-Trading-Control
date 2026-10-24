"""Durable single-active-worker lease per role, using the existing 20-table StateDB.

A lease protects worker ownership, not broker idempotency. The host must check
ownership before work and keep using the existing gateway intent journal and
reconciliation path. No broker client, scheduler, or network call is created.
"""
import math
import time
import uuid


class WorkerSupervisor:
    def __init__(self, db):
        self.db = db

    def install_schema(self):
        """Explicit additive index. Rehearse backup/restore before production.

        Historical duplicate active roles cause a uniqueness failure, not an
        automatic deletion or an arbitrary winner.
        """
        with self.db.lock:
            try:
                self.db.conn.execute("BEGIN IMMEDIATE")
                self.db.conn.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_worker_one_active_role "
                    "ON worker(role) WHERE status='active'"
                )
                self.db.conn.commit()
            except Exception:
                self.db.conn.rollback()
                raise

    @staticmethod
    def _args(role, ttl):
        if not isinstance(role, str) or not role.strip() or role != role.strip():
            raise ValueError("Nonempty canonical worker role required")
        if isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or not math.isfinite(ttl) or ttl <= 0:
            raise ValueError("Finite positive worker lease required")

    @staticmethod
    def _time(now):
        now = time.time() if now is None else now
        if isinstance(now, bool) or not isinstance(now, (int, float)) or not math.isfinite(now) or now <= 0:
            raise ValueError("Finite positive timestamp required")
        return now

    def acquire(self, role, *, ttl=60, now=None):
        """Atomically return a unique worker ID or None if role is held.

        Worker IDs are fresh opaque fencing tokens; never reuse on restart.
        An expired worker cannot heartbeat/release its replacement.
        """
        self._args(role, ttl)
        now = self._time(now)
        worker_id = uuid.uuid4().hex
        with self.db.lock:
            conn = self.db.conn
            try:
                conn.execute("BEGIN IMMEDIATE")
                if not conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='index' AND name='idx_worker_one_active_role'"
                ).fetchone():
                    raise RuntimeError("Worker role uniqueness index not installed")
                conn.execute(
                    "UPDATE worker SET status='expired' WHERE role=? AND status='active' "
                    "AND (lease_expires_at IS NULL OR lease_expires_at<=?)", (role, now)
                )
                if conn.execute(
                    "SELECT 1 FROM worker WHERE role=? AND status='active'", (role,)
                ).fetchone():
                    conn.commit()
                    return None
                conn.execute(
                    "INSERT INTO worker(id,role,status,last_heartbeat,lease_expires_at) "
                    "VALUES(?,?,'active',?,?)", (worker_id, role, int(now), now + ttl)
                )
                conn.commit()
                return worker_id
            except Exception:
                conn.rollback()
                raise

    def heartbeat(self, worker_id, *, ttl=60, now=None):
        if not isinstance(worker_id, str) or not worker_id:
            raise ValueError("Worker token required")
        self._args("worker", ttl)
        now = self._time(now)
        with self.db.lock:
            conn = self.db.conn
            try:
                conn.execute("BEGIN IMMEDIATE")
                updated = conn.execute(
                    "UPDATE worker SET last_heartbeat=?,lease_expires_at=? "
                    "WHERE id=? AND status='active' AND lease_expires_at>?",
                    (int(now), now + ttl, worker_id, now)
                ).rowcount
                conn.commit()
                return updated == 1
            except Exception:
                conn.rollback()
                raise

    def owns(self, worker_id, *, now=None):
        now = self._time(now)
        with self.db.lock:
            row = self.db.conn.execute(
                "SELECT 1 FROM worker WHERE id=? AND status='active' AND lease_expires_at>?",
                (worker_id, now)
            ).fetchone()
            return row is not None

    def release(self, worker_id, *, now=None):
        now = self._time(now)
        with self.db.lock:
            conn = self.db.conn
            try:
                conn.execute("BEGIN IMMEDIATE")
                changed = conn.execute(
                    "UPDATE worker SET status='stopped',lease_expires_at=? "
                    "WHERE id=? AND status='active' AND lease_expires_at>?",
                    (now, worker_id, now)
                ).rowcount
                conn.commit()
                return changed == 1
            except Exception:
                conn.rollback()
                raise

    def status(self, role, *, now=None):
        self._args(role, 1)
        now = self._time(now)
        with self.db.lock:
            rows = self.db.conn.execute(
                "SELECT id,role,status,last_heartbeat,lease_expires_at FROM worker "
                "WHERE role=? ORDER BY lease_expires_at DESC", (role,)
            ).fetchall()
            return [{**dict(row), "currently_owned": row['status'] == 'active' and
                     row['lease_expires_at'] is not None and row['lease_expires_at'] > now}
                    for row in rows]

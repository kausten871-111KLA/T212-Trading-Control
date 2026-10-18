"""Idempotent, broker-neutral audit for interrupted DEMO intent dispatches.

A stale intent without an order is *not* proof that no broker request occurred.
This component only records a reconciliation requirement. It never submits,
retries, cancels or verifies broker orders, and it does not change strategies.
"""
import json
import time


class PreJournalRecoveryAudit:
    KIND = "PRE_JOURNAL_INTENT"
    STATE = "AWAITING_BROKER_VERIFICATION"

    def __init__(self, db):
        """Use the existing shared StateDB (connection and RLock)."""
        self.db = db

    def scan(self, *, now=None, minimum_age_seconds=300):
        """Return IDs newly flagged for reconciliation; no broker access.

        The age threshold is a diagnostic grace period, NOT a trade limit.
        BEGIN IMMEDIATE serializes scans across SQLite connections; existing
        unresolved receipts and active execution leases prevent false alerts.
        """
        if not isinstance(minimum_age_seconds, (int, float)) or minimum_age_seconds < 0:
            raise ValueError("Nonnegative diagnostic age required")
        now = time.time() if now is None else now
        if not isinstance(now, (int, float)) or not (0 < now < float('inf')):
            raise ValueError("Valid current timestamp required")
        created = []
        with self.db.lock:
            conn = self.db.conn
            try:
                conn.execute("BEGIN IMMEDIATE")
                active = set()
                for row in conn.execute(
                    "SELECT payload FROM event_queue WHERE event_type='EXECUTE_ORDER' "
                    "AND status='claimed' AND lease_expires_at>?", (now,)
                ):
                    try:
                        payload = json.loads(row['payload'])
                        if isinstance(payload, dict) and isinstance(payload.get('intent_id'), str):
                            active.add(payload['intent_id'])
                    except (TypeError, ValueError):
                        # Malformed events are a separate queue-validation fault.
                        pass
                candidates = conn.execute(
                    "SELECT id,created_at FROM intent WHERE status='DISPATCHING' "
                    "AND created_at<=? ORDER BY created_at,id",
                    (now - minimum_age_seconds,),
                ).fetchall()
                for row in candidates:
                    intent_id = row['id']
                    if intent_id in active:
                        continue
                    if conn.execute('SELECT 1 FROM "order" WHERE intent_id=? LIMIT 1',
                                    (intent_id,)).fetchone():
                        continue
                    if conn.execute(
                        "SELECT 1 FROM recovery_record WHERE intent_id=? AND "
                        "(recovery_type=? OR recovery_type='BROKER_ID_UNRESOLVED') LIMIT 1",
                        (intent_id, self.KIND),
                    ).fetchone():
                        continue
                    detail = json.dumps({
                        'reason': 'stale_dispatch_without_broker_order_receipt',
                        'intent_created_at': row['created_at'],
                        'observed_at': int(now),
                        'next_action': 'reconcile_existing_gateway_journal_and_broker_before_any_retry',
                    }, sort_keys=True)
                    conn.execute(
                        "INSERT INTO recovery_record(intent_id,recovery_type,state,detail,created_at) "
                        "VALUES(?,?,?,?,?)",
                        (intent_id, self.KIND, self.STATE, detail, int(now)),
                    )
                    created.append(intent_id)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return created

    def pending(self):
        """List flagged intents, explicitly NOT broker-verified results."""
        with self.db.lock:
            rows = self.db.conn.execute(
                "SELECT id,intent_id,state,created_at FROM recovery_record "
                "WHERE recovery_type=? ORDER BY id", (self.KIND,)
            ).fetchall()
            return [dict(row) for row in rows]

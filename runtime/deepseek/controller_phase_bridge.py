"""Authenticated-host seam for idempotent phase events from EXISTING WebUI automations.

No scheduler, broker client, model call, or credentials are created here.
The WebUI host must supply an authorizer that checks the authenticated principal;
this module is NOT itself a WebUI tool or a deployed authentication endpoint.
"""

import datetime
import json
import time

# Existing WebUI automation IDs from DeepSeek's deployment handoff. Do not create
# replacement schedules or treat these IDs alone as authentication credentials.
PHASE_BY_AUTOMATION = {
    "94493540-36ef-4ab9-a9fb-06665a038a50": ("MARKET_OPEN", 20),
    "59f7e6a5-021c-4edd-92f3-dfa2f7e05f5f": ("MARKET_MIDDAY", 40),
    "e73d6c8e-457f-42b3-8177-645e7743e2a8": ("MARKET_CLOSE", 20),
}


class ControllerPhaseBridge:
    """Inject a host-backed authorizer; transactionally dedupe phase delivery.

    ``authorizer(principal, automation_id)`` must return the literal ``True``
    only for an authenticated, authorized WebUI controller invocation. Caller-
    supplied automation IDs are NOT evidence of authentication by themselves.
    """

    def __init__(self, db, authorizer):
        if not callable(authorizer):
            raise ValueError("Authenticated host authorizer is required")
        self.db = db
        self.authorizer = authorizer

    def _validate(self, automation_id, market_date, principal):
        if automation_id not in PHASE_BY_AUTOMATION:
            raise PermissionError("Unrecognized existing automation")
        if self.authorizer(principal, automation_id) is not True:
            raise PermissionError("Controller identity not authorized")
        if not isinstance(market_date, str):
            raise ValueError("market_date must be YYYY-MM-DD")
        try:
            parsed = datetime.date.fromisoformat(market_date)
        except ValueError as exc:
            raise ValueError("Invalid market_date") from exc
        if parsed.isoformat() != market_date:
            raise ValueError("market_date must be YYYY-MM-DD")
        return PHASE_BY_AUTOMATION[automation_id]

    def enqueue(self, *, automation_id, market_date, principal):
        """Return (event_id, created). Replays never enqueue another event.

        Atomic BEGIN IMMEDIATE serializes concurrent workers across SQLite
        connections. Existing event status is preserved, including failures.
        The canonical payload excludes timestamps and chat-run IDs so a fresh
        chat for the same phase/date cannot cause a duplicate market event.
        """
        event_type, priority = self._validate(automation_id, market_date, principal)
        correlation_id = f"webui-phase:{automation_id}:{market_date}"
        payload = {"automation_id": automation_id, "market_date": market_date}
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        with self.db.lock:
            try:
                self.db.conn.execute("BEGIN IMMEDIATE")
                existing = self.db.conn.execute(
                    "SELECT id,payload FROM event_queue WHERE event_type=? AND correlation_id=? "
                    "ORDER BY id LIMIT 1", (event_type, correlation_id)
                ).fetchone()
                if existing is not None:
                    if json.loads(existing["payload"]) != payload:
                        raise ValueError("Conflicting existing phase event payload")
                    self.db.conn.commit()
                    return existing["id"], False
                cur = self.db.conn.execute(
                    "INSERT INTO event_queue(event_type,payload,priority,correlation_id,created_at) "
                    "VALUES(?,?,?,?,?)",
                    (event_type, canonical, priority, correlation_id, int(time.time())),
                )
                self.db.conn.commit()
                return cur.lastrowid, True
            except Exception:
                self.db.conn.rollback()
                raise

    def status(self, *, automation_id, market_date, principal):
        """Return minimal persisted status to the authenticated controller."""
        event_type, _ = self._validate(automation_id, market_date, principal)
        correlation_id = f"webui-phase:{automation_id}:{market_date}"
        with self.db.lock:
            row = self.db.conn.execute(
                "SELECT id,status,attempts,last_error FROM event_queue "
                "WHERE event_type=? AND correlation_id=? ORDER BY id LIMIT 1",
                (event_type, correlation_id),
            ).fetchone()
            return dict(row) if row is not None else None

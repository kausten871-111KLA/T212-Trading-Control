"""Authenticated, idempotent phase-instruction acknowledgements.

This is a durable *controller-processing* receipt, NOT a broker fill or a
trade authorization. The host supplies the authenticated WebUI principal
and authorizer. No model calls, broker requests, or schedules occur here.
"""
import datetime
import json
import time

from .controller_phase_bridge import PHASE_BY_AUTOMATION


class ControllerAcknowledgements:
    def __init__(self, db, authorizer):
        if not callable(authorizer):
            raise ValueError("Authenticated host authorizer is required")
        self.db = db
        self.authorizer = authorizer

    def install_schema(self):
        """Add only an index; operator must rehearse backup/restore first."""
        with self.db.lock:
            self.db.conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_controller_ack_once "
                "ON controller_result(controller_instruction_id) "
                "WHERE kind='CONTROLLER_ACK' AND controller_instruction_id IS NOT NULL"
            )
            self.db.conn.commit()

    def _load(self, conn, instruction_id, principal):
        if type(instruction_id) is not int or instruction_id <= 0:
            raise ValueError("Positive integer instruction ID required")
        row = conn.execute(
            "SELECT id,instruction_type,payload,status FROM controller_instruction WHERE id=?",
            (instruction_id,),
        ).fetchone()
        if row is None or row['instruction_type'] != 'PHASE_EVENT':
            raise ValueError("Unknown phase instruction")
        try:
            payload = json.loads(row['payload'])
            automation_id = payload['automation_id']
            event_type = payload['event_type']
            market_date = payload['market_date']
            event_id = payload['source_event_id']
        except (TypeError, ValueError, KeyError) as exc:
            raise ValueError("Malformed phase instruction") from exc
        if (automation_id not in PHASE_BY_AUTOMATION or
                PHASE_BY_AUTOMATION[automation_id][0] != event_type or
                not isinstance(market_date, str) or
                datetime.date.fromisoformat(market_date).isoformat() != market_date or
                type(event_id) is not int or event_id <= 0):
            raise ValueError("Phase instruction identity mismatch")
        # IDs are not credentials. Authentication is provided by WebUI host.
        if self.authorizer(principal, automation_id) is not True:
            raise PermissionError("Controller principal not authorized")
        event = conn.execute(
            "SELECT id FROM event_queue WHERE id=? AND event_type=? AND "
            "correlation_id=? AND status='done'",
            (event_id, event_type, f'webui-phase:{automation_id}:{market_date}'),
        ).fetchone()
        dispatch = conn.execute(
            "SELECT id FROM controller_result WHERE event_id=? AND "
            "controller_instruction_id=? AND kind='PHASE_DISPATCH'",
            (event_id, instruction_id),
        ).fetchone()
        if event is None or dispatch is None:
            raise ValueError("Unverified dispatch linkage")
        return row, payload

    def status(self, *, instruction_id, principal):
        with self.db.lock:
            row, _ = self._load(self.db.conn, instruction_id, principal)
            receipt = self.db.conn.execute(
                "SELECT id,payload FROM controller_result WHERE "
                "controller_instruction_id=? AND kind='CONTROLLER_ACK'",
                (instruction_id,),
            ).fetchone()
            return {'instruction_id': instruction_id, 'status': row['status'],
                    'receipt_id': receipt['id'] if receipt else None,
                    'outcome': json.loads(receipt['payload']) if receipt else None}

    def acknowledge(self, *, instruction_id, principal, outcome):
        """Persist one processing outcome; replay is safe, conflicts rejected.

        `outcome` is a JSON object containing a controller processing result;
        it does not mean a broker order was accepted or executed.
        """
        if not isinstance(outcome, dict) or not outcome:
            raise ValueError("Nonempty outcome object required")
        canonical = json.dumps(outcome, sort_keys=True, separators=(',', ':'), allow_nan=False)
        with self.db.lock:
            conn = self.db.conn
            try:
                conn.execute('BEGIN IMMEDIATE')
                if not conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='index' "
                    "AND name='idx_controller_ack_once'"
                ).fetchone():
                    raise RuntimeError("Acknowledgement unique index not installed")
                row, payload = self._load(conn, instruction_id, principal)
                existing = conn.execute(
                    "SELECT id,payload FROM controller_result WHERE "
                    "controller_instruction_id=? AND kind='CONTROLLER_ACK'",
                    (instruction_id,),
                ).fetchone()
                if existing:
                    if existing['payload'] != canonical:
                        raise ValueError("Conflicting controller acknowledgement")
                    conn.commit()
                    return existing['id'], False
                if row['status'] != 'issued':
                    raise ValueError("Controller instruction is not pending")
                now = int(time.time())
                changed = conn.execute(
                    "UPDATE controller_instruction SET status='acknowledged',acknowledged_at=? "
                    "WHERE id=? AND status='issued'", (now, instruction_id),
                ).rowcount
                if changed != 1:
                    raise RuntimeError("Instruction ownership changed")
                cur = conn.execute(
                    "INSERT INTO controller_result(controller_instruction_id,event_id,kind,payload,created_at) "
                    "VALUES(?,?,'CONTROLLER_ACK',?,?)",
                    (instruction_id, payload['source_event_id'], canonical, now),
                )
                conn.commit()
                return cur.lastrowid, True
            except Exception:
                conn.rollback()
                raise

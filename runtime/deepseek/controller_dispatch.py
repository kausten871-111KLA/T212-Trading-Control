"""Durable phase-event -> controller instruction outbox (staged, no model/broker calls).

Existing WebUI automations are the only schedule authority. The authenticated
ControllerPhaseBridge must enqueue each phase; this dispatcher only accepts
its canonical event identity and an unexpired worker lease. Host integration
must separately authenticate consumers of controller_instruction.
"""
import datetime
import json
import time

from .controller_phase_bridge import PHASE_BY_AUTOMATION


class ControllerPhaseDispatcher:
    EVENT_TYPES = frozenset(v[0] for v in PHASE_BY_AUTOMATION.values())

    def __init__(self, db, supervisor=None):
        self.db = db
        self.supervisor = supervisor

    def install_schema(self):
        """Explicit additive migration; invoke only after backup/restore rehearsal.

        A uniqueness violation reveals historical duplicate receipts and must
        be investigated, not silently discarded.
        """
        with self.db.lock:
            self.db.conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_ctl_result_phase_event "
                "ON controller_result(event_id) WHERE kind='PHASE_DISPATCH' "
                "AND event_id IS NOT NULL"
            )
            self.db.conn.commit()

    def dispatch_claim(self, event):
        """Atomically persist one controller instruction and complete leased event.

        Returns (instruction_id, created), or None for stale/invalid ownership.
        Never calls DeepSeek, a gateway, a data vendor, or a broker.
        """
        now = time.time()
        with self.db.lock:
            conn = self.db.conn
            try:
                conn.execute("BEGIN IMMEDIATE")
                # Explicit migration is required: don't run without dedupe index.
                if not conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='index' "
                    "AND name='idx_ctl_result_phase_event'"
                ).fetchone():
                    raise RuntimeError("Controller outbox unique index not installed")
                # Optional host-installed supervisor fences stale process owners.
                # This check shares the dispatch transaction with the event claim.
                if self.supervisor is not None:
                    owner = conn.execute(
                        "SELECT 1 FROM worker WHERE id=? AND role='controller' "
                        "AND status='active' AND lease_expires_at>?",
                        (event['worker_id'], now),
                    ).fetchone()
                    if owner is None:
                        conn.commit()
                        return None
                row = conn.execute(
                    "SELECT * FROM event_queue WHERE id=? AND status='claimed' "
                    "AND worker_id=? AND claim_token=? AND lease_expires_at>?",
                    (event['id'], event['worker_id'], event['claim_token'], now),
                ).fetchone()
                if row is None:
                    conn.commit()
                    return None
                if row['event_type'] not in self.EVENT_TYPES:
                    raise ValueError("Not a controller phase event")
                payload = json.loads(row['payload'])
                if not isinstance(payload, dict):
                    raise ValueError("Malformed phase payload")
                automation_id = payload.get('automation_id')
                market_date = payload.get('market_date')
                if (automation_id not in PHASE_BY_AUTOMATION or
                    PHASE_BY_AUTOMATION[automation_id][0] != row['event_type'] or
                    not isinstance(market_date, str) or
                    datetime.date.fromisoformat(market_date).isoformat() != market_date or
                    row['correlation_id'] != f'webui-phase:{automation_id}:{market_date}'):
                    raise ValueError("Phase event identity mismatch")
                existing = conn.execute(
                    "SELECT controller_instruction_id FROM controller_result "
                    "WHERE event_id=? AND kind='PHASE_DISPATCH'",
                    (row['id'],),
                ).fetchone()
                if existing:
                    instruction_id, created = existing[0], False
                else:
                    instruction = {
                        'source_event_id': row['id'],
                        'event_type': row['event_type'],
                        'automation_id': automation_id,
                        'market_date': market_date,
                    }
                    cur = conn.execute(
                        "INSERT INTO controller_instruction(instruction_type,payload,status,issued_at) "
                        "VALUES('PHASE_EVENT',?,'issued',?)",
                        (json.dumps(instruction, sort_keys=True), int(now)),
                    )
                    instruction_id, created = cur.lastrowid, True
                    conn.execute(
                        "INSERT INTO controller_result(controller_instruction_id,event_id,kind,payload,created_at) "
                        "VALUES(?,?,'PHASE_DISPATCH',?,?)",
                        (instruction_id, row['id'], json.dumps({'state': 'queued_for_controller'}), int(now)),
                    )
                changed = conn.execute(
                    "UPDATE event_queue SET status='done' WHERE id=? AND status='claimed' "
                    "AND worker_id=? AND claim_token=? AND lease_expires_at>?",
                    (row['id'], event['worker_id'], event['claim_token'], now),
                ).rowcount
                if changed != 1:
                    raise RuntimeError("Lost phase-event lease during dispatch")
                conn.commit()
                return instruction_id, created
            except Exception:
                conn.rollback()
                raise

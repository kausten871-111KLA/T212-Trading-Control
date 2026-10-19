"""Durable, at-most-once claim for a PHASE_EVENT model invocation.

Staged host contract: claim BEFORE invoking the existing WebUI completion handler.
A claim that survives a crash is UNKNOWN, not permission to invoke again.
The host supplies a trusted principal and terminal-stream verifier; neither a
chat/tool caller nor this module may impersonate that host. No broker/model I/O.
"""
import json
import time
import uuid
import datetime

from .controller_phase_bridge import PHASE_BY_AUTOMATION


class ModelInvocationGate:
    CLAIM = 'MODEL_INVOCATION_CLAIM'
    RESULT = 'MODEL_INVOCATION_RESULT'

    def __init__(self, db, *, authorizer, verify_terminal):
        if not callable(authorizer) or not callable(verify_terminal):
            raise ValueError('Authenticated authorizer and terminal verifier required')
        self.db = db
        self.authorizer = authorizer
        self.verify_terminal = verify_terminal

    def install_schema(self):
        """Additive migration; run only after backed-up schema rehearsal."""
        with self.db.lock:
            self.db.conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_model_invocation_claim_once "
                "ON controller_result(controller_instruction_id) "
                "WHERE kind='MODEL_INVOCATION_CLAIM' AND controller_instruction_id IS NOT NULL"
            )
            self.db.conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_model_invocation_result_once "
                "ON controller_result(controller_instruction_id) "
                "WHERE kind='MODEL_INVOCATION_RESULT' AND controller_instruction_id IS NOT NULL"
            )
            self.db.conn.commit()

    @staticmethod
    def _canonical(obj):
        return json.dumps(obj, sort_keys=True, separators=(',', ':'), allow_nan=False)

    @staticmethod
    def _uuid(value):
        try:
            parsed = uuid.UUID(value)
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError('Host-generated UUID required') from exc
        if str(parsed) != value:
            raise ValueError('Canonical UUID required')

    def _validate(self, conn, instruction_id, principal):
        if type(instruction_id) is not int or instruction_id <= 0:
            raise ValueError('Positive instruction ID required')
        instruction = conn.execute(
            "SELECT id,instruction_type,payload,status FROM controller_instruction WHERE id=?",
            (instruction_id,),
        ).fetchone()
        if instruction is None or instruction['instruction_type'] != 'PHASE_EVENT':
            raise ValueError('Unknown PHASE_EVENT instruction')
        try:
            payload = json.loads(instruction['payload'])
            aid, event_id, event_type, date = (
                payload['automation_id'], payload['source_event_id'],
                payload['event_type'], payload['market_date'])
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError('Malformed phase instruction') from exc
        try:
            valid_date = (isinstance(date, str) and
                          datetime.date.fromisoformat(date).isoformat() == date)
        except ValueError:
            valid_date = False
        if (type(event_id) is not int or event_id <= 0 or
                not isinstance(aid, str) or aid not in PHASE_BY_AUTOMATION or
                event_type != PHASE_BY_AUTOMATION[aid][0] or not valid_date):
            raise ValueError('Malformed phase identity')
        if self.authorizer(principal, aid) is not True:
            raise PermissionError('Host principal not authorized')
        link = conn.execute(
            "SELECT 1 FROM event_queue e JOIN controller_result r ON "
            "r.event_id=e.id AND r.controller_instruction_id=? AND "
            "r.kind='PHASE_DISPATCH' WHERE e.id=? AND e.event_type=? "
            "AND e.correlation_id=? AND e.status='done'",
            (instruction_id, event_id, event_type, f'webui-phase:{aid}:{date}'),
        ).fetchone()
        if link is None:
            raise ValueError('Missing authenticated dispatch linkage')
        return instruction, event_id

    def _indexes_present(self, conn):
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name IN (?,?)",
            ('idx_model_invocation_claim_once', 'idx_model_invocation_result_once'))}
        if len(names) != 2:
            raise RuntimeError('Invocation migration incomplete')

    def claim(self, *, instruction_id, principal, invocation_id, chat_id):
        """Return (claim_id, should_invoke). False ALWAYS means do not invoke.

        The claim is committed before model I/O. A process crash after this
        boundary leaves a durable UNKNOWN requiring explicit reconciliation.
        """
        self._uuid(invocation_id)
        if not isinstance(chat_id, str) or not chat_id.strip():
            raise ValueError('Host chat ID required')
        data = self._canonical({'invocation_id': invocation_id, 'chat_id': chat_id})
        with self.db.lock:
            conn = self.db.conn
            try:
                conn.execute('BEGIN IMMEDIATE')
                self._indexes_present(conn)
                instruction, event_id = self._validate(conn, instruction_id, principal)
                old = conn.execute(
                    "SELECT id,payload FROM controller_result WHERE controller_instruction_id=? "
                    "AND kind=?", (instruction_id, self.CLAIM)).fetchone()
                if old is not None:
                    if old['payload'] != data:
                        raise ValueError('Conflicting invocation claim; no retry allowed')
                    conn.commit()
                    return old['id'], False
                if instruction['status'] != 'issued':
                    raise ValueError('Instruction already finalized')
                cur = conn.execute(
                    "INSERT INTO controller_result(controller_instruction_id,event_id,kind,payload,created_at) "
                    "VALUES(?,?,?,?,?)", (instruction_id, event_id, self.CLAIM, data, int(time.time())))
                conn.commit()
                return cur.lastrowid, True
            except Exception:
                conn.rollback()
                raise

    def complete(self, *, instruction_id, principal, invocation_id, chat_id,
                 message_id, terminal):
        """Store host-verified model terminal receipt; never infer broker fills.

        terminal: 'completed' or 'failed'. The host verifier must independently
        establish a terminal streamed model response tied to the given IDs.
        """
        self._uuid(invocation_id)
        if terminal not in ('completed', 'failed'):
            raise ValueError('Explicit terminal model outcome required')
        if not isinstance(message_id, str) or not message_id.strip():
            raise ValueError('Host message ID required')
        if not isinstance(chat_id, str) or not chat_id.strip():
            raise ValueError('Host chat ID required')
        if self.verify_terminal(principal, chat_id, message_id, terminal) is not True:
            raise PermissionError('Terminal model completion not verified')
        data = self._canonical({'invocation_id': invocation_id, 'chat_id': chat_id,
                                'message_id': message_id, 'terminal': terminal})
        with self.db.lock:
            conn = self.db.conn
            try:
                conn.execute('BEGIN IMMEDIATE')
                self._indexes_present(conn)
                _, event_id = self._validate(conn, instruction_id, principal)
                claim = conn.execute(
                    "SELECT payload FROM controller_result WHERE controller_instruction_id=? "
                    "AND kind=?", (instruction_id, self.CLAIM)).fetchone()
                if claim is None or json.loads(claim['payload']) != {
                    'invocation_id': invocation_id, 'chat_id': chat_id}:
                    raise ValueError('No matching durable invocation claim')
                old = conn.execute(
                    "SELECT id,payload FROM controller_result WHERE controller_instruction_id=? "
                    "AND kind=?", (instruction_id, self.RESULT)).fetchone()
                if old is not None:
                    if old['payload'] != data:
                        raise ValueError('Conflicting terminal model receipt')
                    conn.commit()
                    return old['id'], False
                cur = conn.execute(
                    "INSERT INTO controller_result(controller_instruction_id,event_id,kind,payload,created_at) "
                    "VALUES(?,?,?,?,?)", (instruction_id, event_id, self.RESULT,
                                           data, int(time.time())))
                conn.commit()
                return cur.lastrowid, True
            except Exception:
                conn.rollback()
                raise

    def status(self, *, instruction_id, principal):
        with self.db.lock:
            conn = self.db.conn
            self._validate(conn, instruction_id, principal)
            rows = conn.execute(
                "SELECT kind,payload FROM controller_result WHERE controller_instruction_id=? "
                "AND kind IN (?,?)", (instruction_id, self.CLAIM, self.RESULT)).fetchall()
            evidence = {r['kind']: json.loads(r['payload']) for r in rows}
            return {'state': ('terminal' if self.RESULT in evidence else
                              'invocation_unknown' if self.CLAIM in evidence else 'unclaimed'),
                    'claim': evidence.get(self.CLAIM), 'result': evidence.get(self.RESULT)}

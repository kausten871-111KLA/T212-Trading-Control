"""Resume unresolved execution receipts through the existing gateway only.

Never submits/cancels/replaces an order. UNKNOWN remains awaiting verification.
The host injects its configured gateway, using the same durable intent journal.
"""
import json
from .worker_supervisor import WorkerSupervisor


class IntentReconciler:
    def __init__(self, db, gateway):
        self.db, self.gateway = db, gateway
        self.supervisor = WorkerSupervisor(db)

    def run_once(self):
        owner = self.supervisor.acquire('intent_reconciliation', ttl=60)
        if owner is None:
            return {'blocked': 'reconciliation_role_occupied'}
        counts = {'reconciled': 0, 'unresolved': 0, 'failed': 0}
        try:
            with self.db.lock:
                events = [dict(r) for r in self.db.conn.execute(
                    "SELECT * FROM event_queue WHERE event_type='EXECUTE_ORDER' "
                    "AND status='awaiting_verification' ORDER BY id LIMIT 20")]
            for event in events:
                if not self.supervisor.heartbeat(owner, ttl=60):
                    break
                try:
                    proposal = json.loads(event['payload'])
                    with self.db.lock:
                        intent = self.db.conn.execute('SELECT id FROM intent WHERE id=?',
                            (proposal['intent_id'],)).fetchone()
                    if intent is None:
                        raise ValueError('Unresolved event lacks durable intent')
                    result = self.gateway.reconcile(proposal['intent_id'])
                    status = result.get('status', 'UNKNOWN')
                    broker_id = result.get('broker_order_id')
                    # A status without broker identity is not execution proof.
                    if status in ('UNKNOWN', 'NOT_FOUND', 'VALIDATION_FAILED') or broker_id is None:
                        counts['unresolved'] += 1
                        continue
                    if status not in ('NEW', 'PENDING', 'ACCEPTED', 'OPEN', 'FILLED',
                                      'PARTIALLY_FILLED', 'CANCELLED', 'CANCELED', 'REJECTED', 'EXPIRED'):
                        raise ValueError('Unknown broker receipt status')
                    if not self.supervisor.owns(owner):
                        break
                    self.db.upsert_order(broker_id, proposal['intent_id'], proposal['ticker'],
                        proposal['side'], proposal['quantity'], 'MARKET', status,
                        result.get('receipt', {}), result.get('filled_qty', 0))
                    if status not in ('FILLED', 'CANCELLED', 'CANCELED', 'REJECTED', 'EXPIRED'):
                        counts['unresolved'] += 1
                        continue
                    with self.db.lock:
                        self.db.conn.execute("UPDATE event_queue SET status='done' WHERE id=? "
                            "AND status='awaiting_verification'", (event['id'],))
                        self.db.conn.commit()
                    counts['reconciled'] += 1
                except Exception:
                    # Preserve unresolved state. Exception strings can contain secrets.
                    counts['failed'] += 1
            return counts
        finally:
            self.supervisor.release(owner)

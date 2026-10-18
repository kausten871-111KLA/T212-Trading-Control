"""Bounded controller-phase worker using existing StateDB and WebUI schedules.

The host owns authentication, scheduling, process lifetime and DB backup/restore.
This module starts no scheduler, opens no gateway, makes no model calls and does
not acknowledge controller decisions or place orders. Existing DeepSeek runtime
StateDB.claim() and ControllerPhaseDispatcher provide durable event handling.
"""
import time

from .controller_dispatch import ControllerPhaseDispatcher


class ControllerPhaseWorker:
    """Process existing phase events once under an exclusive controller lease."""

    def __init__(self, db, supervisor, *, lease_ttl=60, batch_size=5):
        if lease_ttl <= 0 or batch_size < 1:
            raise ValueError('Positive lease and batch size required')
        self.db = db
        self.supervisor = supervisor
        self.lease_ttl = lease_ttl
        self.batch_size = batch_size
        self.dispatcher = ControllerPhaseDispatcher(db, supervisor=supervisor)

    def _requeue_expired_phase_claims(self):
        """Recover ONLY controller phase claims, never executor/order claims.

        The supplied StateDB.requeue_dead() is global: calling it from a
        controller worker would change an expired EXECUTE_ORDER lease even
        though this worker does not own order reconciliation. Keep the
        existing retry/max-attempt semantics, scoped to phase event types.
        """
        event_types = tuple(sorted(self.dispatcher.EVENT_TYPES))
        marks = ",".join("?" for _ in event_types)
        with self.db.lock:
            conn = self.db.conn
            try:
                conn.execute("BEGIN IMMEDIATE")
                changed = conn.execute(
                    "UPDATE event_queue SET status=CASE WHEN attempts+1>=max_attempts "
                    "THEN 'failed' ELSE 'pending' END, attempts=attempts+1, "
                    "worker_id=NULL,claim_token=NULL,lease_expires_at=NULL "
                    "WHERE status='claimed' AND lease_expires_at<=? "
                    "AND event_type IN (" + marks + ")",
                    (time.time(), *event_types),
                ).rowcount
                conn.commit()
                return changed
            except Exception:
                conn.rollback()
                raise

    def run_once(self):
        """Return counters; never resubmit an order or consume EXECUTE_ORDER.

        The host must install the supervisor and dispatcher indexes explicitly
        after backup/restore rehearsal. Expired queue claims are recovered by
        existing StateDB.requeue_dead(), which does not submit orders.
        """
        worker_id = self.supervisor.acquire('controller', ttl=self.lease_ttl)
        if worker_id is None:
            return {'claimed': 0, 'dispatched': 0, 'blocked': 'controller_role_occupied'}
        counts = {'claimed': 0, 'dispatched': 0, 'stale': 0, 'failed': 0}
        try:
            self._requeue_expired_phase_claims()
            if not self.supervisor.heartbeat(worker_id, ttl=self.lease_ttl):
                counts['blocked'] = 'worker_lease_expired'
                return counts
            events = self.db.claim(
                worker_id, tuple(sorted(self.dispatcher.EVENT_TYPES)),
                lease_ttl=self.lease_ttl, limit=self.batch_size,
            )
            counts['claimed'] = len(events)
            for event in events:
                # Dispatch verifies BOTH supervisor role ownership and the
                # queue's event-specific lease token inside one transaction.
                if not self.supervisor.heartbeat(worker_id, ttl=self.lease_ttl):
                    counts['stale'] += 1
                    continue
                try:
                    result = self.dispatcher.dispatch_claim(event)
                    if result is None:
                        counts['stale'] += 1
                    else:
                        counts['dispatched'] += 1
                except Exception as exc:
                    counts['failed'] += 1
                    # Existing StateDB.fail checks owner + token + expiry.
                    self.db.fail(event['id'], worker_id, event['claim_token'], str(exc))
            return counts
        finally:
            self.supervisor.release(worker_id)

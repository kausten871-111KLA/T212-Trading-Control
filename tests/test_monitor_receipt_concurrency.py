import asyncio
import tempfile
import unittest
from pathlib import Path
from openwebui.tools.position_monitor_core import MonitorLedger, monitor_once

class ReceiptConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'ledger.sqlite'
        self.ledger = MonitorLedger(self.path)
        self.ledger.register('watch', 'ACME_US_EQ', 'AT_OR_BELOW', 95, 'intent', 'controller-v1')
        self.ledger.claim('watch', 90)

    async def test_two_workers_terminal_response_does_not_break_cycle(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def slow_reconcile(intent):
            entered.set()
            await release.wait()
            return {'state': 'PENDING'}
        async def positions(): return []
        async def submit(*args): self.fail('Outstanding intent must not be resubmitted')
        task = asyncio.create_task(monitor_once(self.ledger, positions, submit, slow_reconcile))
        await entered.wait()
        MonitorLedger(self.path).record('watch', 'FILLED', {'state': 'FILLED', 'brokerOrderId': 123})
        release.set()
        result = await task
        self.assertEqual(result['unavailable'], [])
        self.assertEqual(result['reconciled'], 0)
        self.assertEqual(result['stale_receipts'], 1)
        self.assertEqual(self.ledger.rows(('FILLED',))[0]['broker_receipt'], '{"brokerOrderId": 123, "state": "FILLED"}')

    async def test_stale_unknown_cannot_replace_new_acknowledgement(self):
        before = self.ledger.rows(('CLAIMED',))[0]
        self.ledger.record('watch', 'ACKNOWLEDGED', {'brokerOrderId': 123})
        accepted = self.ledger.record('watch', 'UNKNOWN', {'error': 'old timeout'}, expected_revision=before['revision'])
        self.assertFalse(accepted)
        self.assertEqual(len(self.ledger.rows(('ACKNOWLEDGED',))), 1)

    async def test_current_revision_accepts_reconciliation_after_restart(self):
        restarted = MonitorLedger(self.path)
        row = restarted.rows(('CLAIMED',))[0]
        self.assertTrue(restarted.record('watch', 'FILLED', {'brokerOrderId': 123}, expected_revision=row['revision']))
        self.assertEqual(len(self.ledger.rows(('FILLED',))), 1)

    async def test_delayed_dispatch_receipt_cannot_replace_terminal_result(self):
        self.ledger.record('watch', 'FILLED', {'brokerOrderId': 123})
        self.assertFalse(self.ledger.record('watch', 'UNKNOWN', {'error': 'late dispatch timeout'}))
        self.assertEqual(len(self.ledger.rows(('FILLED',))), 1)

    async def test_rejected_stale_receipt_adds_no_event(self):
        row = self.ledger.rows(('CLAIMED',))[0]
        self.ledger.record('watch', 'ACKNOWLEDGED', {'brokerOrderId': 123})
        db = self.ledger.db()
        count = db.execute('SELECT COUNT(*) FROM events').fetchone()[0]
        db.close()
        self.ledger.record('watch', 'UNKNOWN', {}, expected_revision=row['revision'])
        db = self.ledger.db()
        self.assertEqual(db.execute('SELECT COUNT(*) FROM events').fetchone()[0], count)
        db.close()

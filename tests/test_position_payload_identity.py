"""Broker shape/identity regressions. All callbacks are local fakes."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / 'openwebui/tools/position_monitor_core.py'
SPEC = importlib.util.spec_from_file_location('identity_monitor', SOURCE)
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class PositionIdentityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ledger = M.MonitorLedger(Path(self.temp.name) / 'monitor.sqlite')
        self.ledger.register('watch', 'ACME_US_EQ', 'AT_OR_BELOW', 95, 'intent', 'deepseek-v5')
        self.calls = []

    def position(self, **changes):
        result = {'ticker': 'ACME_US_EQ', 'quantityAvailableForTrading': 2, 'currentPrice': 90}
        result.update(changes)
        return result

    async def run_positions(self, rows):
        async def positions():
            return rows
        async def submit(*args):
            self.calls.append(args)
            return {'state': 'FILLED', 'brokerOrderId': 'synthetic-order'}
        async def reconcile(intent):
            return {'state': 'UNKNOWN'}
        return await M.monitor_once(self.ledger, positions, submit, reconcile)

    async def assert_ambiguous(self, rows):
        outcome = await self.run_positions(rows)
        self.assertEqual(self.calls, [])
        self.assertEqual(outcome['submitted'], 0)
        self.assertEqual(self.ledger.rows()[0]['state'], 'ACTIVE')
        self.assertIn({'watch_id': 'watch', 'reason': 'ambiguous_position_ticker'}, outcome['unavailable'])

    async def test_duplicate_top_level_ticker_never_selects_first_quantity(self):
        await self.assert_ambiguous([self.position(), self.position(quantityAvailableForTrading=9)])

    async def test_duplicate_identical_rows_still_require_reconciliation(self):
        await self.assert_ambiguous([self.position(), self.position()])

    async def test_duplicate_nested_and_top_level_identity(self):
        await self.assert_ambiguous([self.position(), self.position(ticker=None, instrument={'ticker': 'ACME_US_EQ'})])

    async def test_conflicting_ticker_claims_block_both_symbols(self):
        self.ledger.register('other-watch', 'OTHER_US_EQ', 'AT_OR_BELOW', 95, 'other-intent', 'deepseek-v5')
        outcome = await self.run_positions([self.position(instrument={'ticker': 'OTHER_US_EQ'})])
        self.assertEqual(self.calls, [])
        self.assertEqual(len(self.ledger.rows()), 2)
        self.assertEqual({x['watch_id'] for x in outcome['unavailable']}, {'watch', 'other-watch'})
        self.assertTrue(all(x['reason'] == 'ambiguous_position_ticker' for x in outcome['unavailable']))

    async def test_later_valid_row_does_not_clear_identity_conflict(self):
        await self.assert_ambiguous([self.position(instrument={'ticker': 'OTHER_US_EQ'}), self.position()])

    async def test_bad_instrument_without_ticker_does_not_abort_valid_watch(self):
        rows = [{'instrument': value} for value in ['broken', ['broken'], 123, True]]
        outcome = await self.run_positions(rows + [self.position()])
        self.assertEqual(outcome['submitted'], 1)
        self.assertEqual(self.calls, [('ACME_US_EQ', 2.0, 'intent')])

    async def test_unhashable_ticker_does_not_abort_valid_watch(self):
        rows = [{'ticker': value} for value in [['ACME_US_EQ'], {'ticker': 'ACME_US_EQ'}]]
        outcome = await self.run_positions(rows + [self.position()])
        self.assertEqual(outcome['submitted'], 1)

    async def test_invalid_instrument_on_target_does_not_submit(self):
        await self.assert_ambiguous([self.position(instrument=['ACME_US_EQ'])])

    async def test_malformed_nested_ticker_on_target_does_not_submit(self):
        await self.assert_ambiguous([self.position(instrument={'ticker': ['ACME_US_EQ']})])

    async def test_unique_nested_identity_submits(self):
        result = await self.run_positions([self.position(ticker=None, instrument={'ticker': 'ACME_US_EQ'})])
        self.assertEqual(result['submitted'], 1)

    async def test_matching_top_and_nested_identity_is_one_position(self):
        result = await self.run_positions([self.position(instrument={'ticker': 'ACME_US_EQ'})])
        self.assertEqual(result['submitted'], 1)

    async def test_ambiguous_symbol_does_not_block_unrelated_valid_watch(self):
        self.ledger.register('other-watch', 'OTHER_US_EQ', 'AT_OR_BELOW', 95, 'other-intent', 'deepseek-v5')
        result = await self.run_positions([self.position(), self.position(), self.position(ticker='OTHER_US_EQ')])
        self.assertEqual(result['submitted'], 1)
        self.assertEqual(self.calls, [('OTHER_US_EQ', 2.0, 'other-intent')])


if __name__ == '__main__':
    unittest.main()

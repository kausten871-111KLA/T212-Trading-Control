import json
import tempfile
import unittest
from pathlib import Path

from openwebui.tools.deterministic_opportunity_scanner import DeterministicScanner, ScannerConfig
from openwebui.tools.movement_tier_state import MovementTierState
from openwebui.tools.catalyst_handoff_queue import CatalystHandoffQueue
from openwebui.tools.t212_instrument_cache import InstrumentCache
from openwebui.tools.missed_green_audit import MissedGreenAudit
from openwebui.tools.opportunity_ledger import OpportunityLedger
from openwebui.tools.scanner_metrics import average_daily_volume_from_bars, enrich_snapshot


class ScannerCoreTests(unittest.TestCase):
    def test_average_daily_volume(self):
        bars = [{'v': 100}, {'v': 200}, {'v': 300}]
        self.assertEqual(average_daily_volume_from_bars(bars, 3), 200)

    def test_metric_enrichment(self):
        row = enrich_snapshot(
            {'symbol':'ABC','price':10,'dayVolume':100000,'previousClose':8,'bid':9.9,'ask':10.1},
            avg20_volume=50000,
            t212_ticker='ABC_US_EQ',
            tradable=True,
        )
        self.assertAlmostEqual(row['change_pct'], 25.0)
        self.assertAlmostEqual(row['rel_vol'], 2.0)
        self.assertTrue(row['tradable'])

    def test_scanner_gate(self):
        scanner = DeterministicScanner(ScannerConfig())
        result = scanner.scan([{
            'symbol':'ABC','price':10,'change_pct':12,'rel_vol':3,
            'spread_pct':1.0,'dollar_vol':2000000,'tradable':True
        }])
        self.assertEqual(result['qualifiedCount'], 1)

    def test_scanner_rejects_warrants_and_stale_assets(self):
        scanner = DeterministicScanner(ScannerConfig())
        rows = [
            {'symbol':'ABC.W','price':10,'change_pct':12,'rel_vol':3,'spread_pct':1,'dollar_vol':2000000,'tradable':True},
            {'symbol':'OLD','asset_status':'legacy','price':10,'change_pct':12,'rel_vol':3,'spread_pct':1,'dollar_vol':2000000,'tradable':True},
        ]
        result = scanner.scan(rows)
        self.assertEqual(result['qualifiedCount'], 0)
        failures = {r['symbol']: r['gate_failures'] for r in result['rejected']}
        self.assertIn('SECURITY_TYPE', failures['ABC.W'])
        self.assertIn('ASSET_STATUS', failures['OLD'])

    def test_movement_tier_boundaries(self):
        with tempfile.TemporaryDirectory() as td:
            state = MovementTierState(path=str(Path(td)/'tiers.json'))
            self.assertEqual(state.tier_for_change(4.99), 0.0)
            self.assertEqual(state.tier_for_change(5.0), 5.0)
            self.assertEqual(state.tier_for_change(9.99), 5.0)
            self.assertEqual(state.tier_for_change(10.0), 10.0)
            self.assertEqual(state.tier_for_change(19.99), 10.0)
            self.assertEqual(state.tier_for_change(20.0), 20.0)
            self.assertEqual(state.tier_for_change(49.99), 20.0)
            self.assertEqual(state.tier_for_change(50.0), 50.0)
            self.assertEqual(state.tier_for_change(81.5), 50.0)
            self.assertEqual(state.tier_for_change(99.99), 50.0)
            self.assertEqual(state.tier_for_change(100.0), 100.0)

    def test_movement_tiers_persist(self):
        with tempfile.TemporaryDirectory() as td:
            state = MovementTierState(path=str(Path(td)/'tiers.json'))
            first = state.update('ABC', 5.1)
            second = state.update('ABC', 7.0)
            third = state.update('ABC', 10.2)
            self.assertTrue(first['newly_qualified'])
            self.assertFalse(second['escalated'])
            self.assertTrue(third['escalated'])

    def test_ledger_persists(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = OpportunityLedger(path=str(Path(td)/'ledger.jsonl'))
            ledger.append('scanner_shortlist', {'symbol':'ABC'})
            rows = ledger.read_recent()
            self.assertEqual(rows[-1]['payload']['symbol'], 'ABC')

    def test_missed_green_codes(self):
        audit = MissedGreenAudit(top_n=10)
        result = audit.classify(
            actual_movers=[{'symbol':'AAA','change_pct':50},{'symbol':'BBB','change_pct':30}],
            surfaced=[{'symbol':'BBB','scanner_state':'rejected'}],
            traded=[],
        )
        by_symbol = {r['symbol']: r['audit_code'] for r in result['rows']}
        self.assertEqual(by_symbol['AAA'], 'SCANNER_DETECTION_FAILURE')
        self.assertEqual(by_symbol['BBB'], 'RULE_THRESHOLD_FALSE_NEGATIVE')

    def test_t212_cache_first_snapshot_is_baseline(self):
        with tempfile.TemporaryDirectory() as td:
            cache = InstrumentCache(
                cache_path=str(Path(td)/'cache.json'),
                diff_path=str(Path(td)/'diff.json'),
            )
            d = cache.save_snapshot([{'ticker':'AAA_US_EQ'}], previous=[])
            self.assertFalse(d['baselineWasPresent'])
            self.assertEqual(d['addedCount'], 0)

    def test_catalyst_queue_dedup_and_ack(self):
        with tempfile.TemporaryDirectory() as td:
            q = CatalystHandoffQueue(path=str(Path(td)/'queue.jsonl'), max_per_day=20)
            candidate = {'symbol':'ABC','tier_state':{'current_tier':5.0}}
            first = q.enqueue(candidate)
            second = q.enqueue(candidate)
            self.assertTrue(first['queued'])
            self.assertFalse(second['queued'])
            event_id = first['event']['id']
            self.assertIsNotNone(q.claim(event_id))
            done = q.acknowledge(event_id, 'done', {'catalyst_state':'verified'})
            self.assertEqual(done['status'], 'done')

    def test_catalyst_queue_daily_budget(self):
        with tempfile.TemporaryDirectory() as td:
            q = CatalystHandoffQueue(path=str(Path(td)/'queue.jsonl'), max_per_day=1)
            self.assertTrue(q.enqueue({'symbol':'AAA','tier_state':{'current_tier':5.0}})['queued'])
            blocked = q.enqueue({'symbol':'BBB','tier_state':{'current_tier':5.0}})
            self.assertFalse(blocked['queued'])
            self.assertEqual(blocked['reason'], 'daily_budget_reached')


if __name__ == '__main__':
    unittest.main()

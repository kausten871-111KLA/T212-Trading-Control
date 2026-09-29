import json
import tempfile
import unittest
from pathlib import Path

from openwebui.tools.deterministic_opportunity_scanner import DeterministicScanner, ScannerConfig
from openwebui.tools.movement_tier_state import MovementTierState
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
        self.assertEqual(by_symbol['AAA'], 'NEV')
        self.assertEqual(by_symbol['BBB'], 'RET')


if __name__ == '__main__':
    unittest.main()
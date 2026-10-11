"""Offline correlation acceptance with real ledger, queue and consumer."""
import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

class Correlation(unittest.TestCase):
    def test_scan_queue_review_reload_preserves_identifiers(self):
        ledger = load('ledger', 'openwebui/tools/opportunity_ledger.py')
        queue = load('queue', 'openwebui/tools/catalyst_handoff_queue.py')
        scanner = types.SimpleNamespace(DeterministicScanner=object, ScannerConfig=object)
        metrics = types.SimpleNamespace(enrich_snapshot=lambda **kwargs: kwargs['snapshot'])
        tier = types.SimpleNamespace(MovementTierState=object)
        session = types.SimpleNamespace(evaluate_session=lambda now: None)
        aliases = {'deterministic_opportunity_scanner': scanner, 'scanner_metrics': metrics,
                   'movement_tier_state': tier, 'opportunity_ledger': ledger,
                   'catalyst_handoff_queue': queue, 'openwebui.tools.catalyst_handoff_queue': queue,
                   'worker.session_gate': session}
        with patch.dict(sys.modules, aliases), tempfile.TemporaryDirectory() as directory:
            pipeline = load('pipeline', 'openwebui/tools/opportunity_scan_pipeline.py')
            consumer = load('consumer', 'worker/run_catalyst_consumer.py')
            log = ledger.OpportunityLedger(Path(directory) / 'events.jsonl')
            jobs = queue.CatalystHandoffQueue(Path(directory) / 'queue.jsonl')
            scan = types.SimpleNamespace(scan=lambda rows: {'shortlist': [{'symbol': 'TEST', 'change_pct': 8}], 'rejected': []})
            tiers = types.SimpleNamespace(update=lambda *args: {'current_tier': 1, 'newly_qualified': True})
            result = pipeline.OpportunityScanPipeline(scan, log, tiers, jobs).run([], {}, {})
            persisted = jobs.pending()[0]
            candidate = persisted['candidate']
            self.assertEqual(candidate['scan_id'], result['scan_id'])
            events = log.read_recent()
            shortlist = next(event for event in events if event['event_type'] == 'scanner_shortlist')
            self.assertEqual(shortlist['event_id'], candidate['scanner_event_id'])
            self.assertEqual(shortlist['correlation_id'], result['scan_id'])
            reviewer = types.SimpleNamespace(review=lambda candidate: {
                'symbol': 'TEST', 'reason_tag': 'offline', 'catalyst_state': 'unknown',
                'headline': '', 'source': '', 'source_ts': '', 'mechanism': '',
                'risk_flags': [], 'disposition': 'unknown', 'confidence': 0})
            output = consumer.consume(jobs, reviewer)
            self.assertEqual(output['orders_submitted'], 0)
            self.assertEqual(output['completed'][0]['scan_id'], result['scan_id'])
            self.assertEqual(output['completed'][0]['scanner_event_id'], shortlist['event_id'])
            reloaded = queue.CatalystHandoffQueue(jobs.path).completed()[0]
            self.assertEqual(reloaded['candidate']['scanner_event_id'], shortlist['event_id'])
            self.assertEqual(reloaded['status'], 'done')

if __name__ == '__main__':
    unittest.main()

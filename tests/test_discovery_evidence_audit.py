import unittest
from runtime.deepseek.discovery_evidence_audit import audit_discovery


class DiscoveryEvidenceAuditTests(unittest.TestCase):
    def test_unknown_without_logs(self):
        r = audit_discovery("RHI", events=[])
        self.assertEqual(r["status"], "no_ingestion_evidence")
        self.assertIsNone(r["candidate_before_major_move"])

    def test_source_observation_not_candidate(self):
        e = [{"symbol": "NAUT", "kind": "source_row", "at": "2026-10-23T13:35:00Z", "source": "runner"}]
        r = audit_discovery("NAUT", events=e)
        self.assertEqual(r["status"], "ingested_but_no_candidate_in_evidence")

    def test_early_candidate_compares_utc(self):
        e = [{"symbol": "NAUT", "kind": "candidate", "at": "2026-10-23T14:35:00+01:00", "source": "runner"}]
        r = audit_discovery("NAUT", events=e, major_move_at="2026-10-23T14:00:00Z")
        self.assertIs(r["candidate_before_major_move"], True)

    def test_late_candidate(self):
        e = [{"symbol": "NAUT", "kind": "candidate", "at": "2026-10-23T15:05:00Z", "source": "runner"}]
        r = audit_discovery("NAUT", events=e, major_move_at="2026-10-23T14:00:00Z")
        self.assertIs(r["candidate_before_major_move"], False)

    def test_missing_timezone_rejected(self):
        e = [{"symbol": "RHI", "kind": "candidate", "at": "2026-10-23T14:30:00", "source": "runner"}]
        with self.assertRaises(ValueError):
            audit_discovery("RHI", events=e)

    def test_inverse_instrument_classification(self):
        r = audit_discovery("3SRR", events=[], instrument_type="inverse_3x_etp", identity_verified=True)
        self.assertEqual(r["instrument_type"], "inverse_3x_etp")

if __name__ == "__main__":
    unittest.main()

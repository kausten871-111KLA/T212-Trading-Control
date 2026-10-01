import unittest

from openwebui.tools.missed_green_audit import MissedGreenAudit


class MissedGreenCanonicalTests(unittest.TestCase):
    def test_legacy_and_canonical_codes_are_both_emitted(self):
        result = MissedGreenAudit(top_n=10).classify(
            actual_movers=[
                {"symbol": "AAA", "change_pct": 50},
                {"symbol": "BBB", "change_pct": 30},
            ],
            surfaced=[
                {"symbol": "BBB", "scanner_state": "rejected"},
            ],
            traded=[],
        )
        rows = {row["symbol"]: row for row in result["rows"]}
        self.assertEqual(rows["AAA"]["audit_code"], "NEV")
        self.assertEqual(rows["AAA"]["root_cause_code"], "SCANNER_DETECTION_FAILURE")
        self.assertEqual(rows["BBB"]["audit_code"], "RET")
        self.assertEqual(rows["BBB"]["root_cause_code"], "RULE_THRESHOLD_FALSE_NEGATIVE")


if __name__ == "__main__":
    unittest.main()

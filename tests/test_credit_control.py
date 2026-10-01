import copy
import json
import unittest
from pathlib import Path

from openwebui.tools.credit_control import (
    CreditValidationError,
    summarize_usage,
    unmetered_completed_model_runs,
    validate_event,
    validate_policy,
)


ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads(
    (ROOT / "webui-control" / "credit-policy.json").read_text(encoding="utf-8")
)


def event(event_id="usage-001", fingerprint="hash-a", cache_hit=False, total=100):
    return {
        "event_id": event_id,
        "run_id": f"run-{event_id}",
        "workspace": "apps-plugins-bots",
        "timestamp": "2026-10-01T01:00:00Z",
        "provider": "approved-provider",
        "model_role": "deep_reasoning",
        "model_id_ref": "server-binding-ref",
        "input_fingerprint": fingerprint,
        "cache_hit": cache_hit,
        "units": {"input": total - 30, "output": 30, "cache_read": 0, "total": total},
        "currency_cost": None,
    }


def run(run_id="run-usage-001", model_role="deep_reasoning"):
    return {
        "run_id": run_id,
        "workspace": "apps-plugins-bots",
        "workflow": "model-work",
        "started_at": "2026-10-01T01:00:00Z",
        "ended_at": "2026-10-01T01:01:00Z",
        "heartbeat_at": "2026-10-01T01:01:00Z",
        "status": "SUCCEEDED",
        "attempt": 1,
        "input_refs": [],
        "output_refs": [],
        "evidence": ["verified"],
        "model_role": model_role,
        "approvals": [],
        "next_action": None,
        "cost": {"currency": "CREDITS", "estimated": 100, "actual": 100},
        "safety": None,
    }


class CreditControlTests(unittest.TestCase):
    def test_policy_is_observe_only_and_preserves_capacity_range(self):
        validate_policy(POLICY)
        self.assertFalse(POLICY["currency_spend_authorised"])
        self.assertEqual(POLICY["monthly_capacity_plan"]["minimum"], 2_000_000_000)
        self.assertEqual(POLICY["monthly_capacity_plan"]["maximum"], 4_000_000_000)

    def test_policy_cannot_authorise_automatic_spend(self):
        changed = copy.deepcopy(POLICY)
        changed["controls"]["automatic_spend_increase"] = True
        with self.assertRaises(CreditValidationError):
            validate_policy(changed)

    def test_credit_components_must_equal_total(self):
        changed = event()
        changed["units"]["total"] = 999
        with self.assertRaises(CreditValidationError):
            validate_event(POLICY, changed)

    def test_prompt_or_secret_content_is_rejected(self):
        changed = event()
        changed["prompt"] = "raw prompt must not be stored"
        with self.assertRaises(CreditValidationError):
            validate_event(POLICY, changed)
        changed = event()
        changed["model_id_ref"] = "api_key=not-allowed"
        with self.assertRaises(CreditValidationError):
            validate_event(POLICY, changed)

    def test_uncached_duplicate_work_is_reported(self):
        first = event("usage-001", fingerprint="same-hash")
        second = event("usage-002", fingerprint="same-hash")
        report = summarize_usage(
            POLICY,
            [first, second],
            "2026-10-01T00:00:00Z",
            "2026-10-31T23:59:59Z",
        )
        self.assertEqual(len(report["uncached_duplicates"]), 1)
        self.assertEqual(report["credits_total"], 200)
        self.assertFalse(report["spend_authorised"])

    def test_cache_hit_is_not_flagged_as_duplicate(self):
        first = event("usage-001", fingerprint="same-hash")
        second = event("usage-002", fingerprint="same-hash", cache_hit=True)
        report = summarize_usage(
            POLICY,
            [first, second],
            "2026-10-01T00:00:00Z",
            "2026-10-31T23:59:59Z",
        )
        self.assertEqual(report["uncached_duplicates"], [])
        self.assertEqual(report["cache_hit_events"], 1)

    def test_currency_costs_remain_separate_without_conversion(self):
        first = event("usage-001")
        first["currency_cost"] = {"currency": "GBP", "amount": 1.25}
        second = event("usage-002", fingerprint="hash-b")
        second["currency_cost"] = {"currency": "USD", "amount": 2.5}
        report = summarize_usage(
            POLICY,
            [first, second],
            "2026-10-01T00:00:00Z",
            "2026-10-31T23:59:59Z",
        )
        self.assertEqual(report["currency_costs"], {"GBP": 1.25, "USD": 2.5})

    def test_unmetered_completed_model_run_is_identified(self):
        missing = unmetered_completed_model_runs([run()], [])
        self.assertEqual(missing, ["run-usage-001"])
        self.assertEqual(
            unmetered_completed_model_runs([run()], [event()]),
            [],
        )


if __name__ == "__main__":
    unittest.main()

import copy
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from openwebui.tools.automation_ledger import (
    LedgerValidationError,
    append_run,
    health_status,
    latest_by_workflow,
    read_runs,
    validate_run,
)


def sample_run(**changes):
    record = {
        "run_id": "run-20260930-230000",
        "workspace": "apps-plugins-bots",
        "workflow": "connector-health",
        "started_at": "2026-09-30T22:00:00Z",
        "ended_at": "2026-09-30T22:01:00Z",
        "heartbeat_at": "2026-09-30T22:01:00Z",
        "status": "SUCCEEDED",
        "attempt": 1,
        "input_refs": ["webui-control/plugin-registry.json"],
        "output_refs": ["handoffs/connector-health.json"],
        "evidence": ["7 registry tests passed"],
        "model_role": None,
        "tool_ids": ["github"],
        "cost": {"currency": "NONE", "estimated": 0, "actual": 0},
        "error": None,
        "approvals": [{"action": "read_only_check", "state": "NOT_REQUIRED"}],
        "next_action": "stage activation checks",
        "safety": None,
    }
    record.update(changes)
    return record


class AutomationLedgerTests(unittest.TestCase):
    def test_valid_record(self):
        validate_run(sample_run())

    def test_append_and_read_private_jsonl(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runs.jsonl"
            append_run(path, sample_run())
            records = read_runs(path)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["run_id"], "run-20260930-230000")
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

    def test_secret_value_is_rejected(self):
        record = sample_run(input_refs=["api_key=do-not-store-this"])
        with self.assertRaises(LedgerValidationError):
            validate_run(record)

    def test_t212_requires_demo_fail_closed_safety(self):
        record = sample_run(
            workspace="t212-demo",
            safety={
                "environment": "DEMO",
                "live_trading": False,
                "order_mutation": False,
            },
        )
        validate_run(record)
        changed = copy.deepcopy(record)
        changed["safety"]["live_trading"] = True
        with self.assertRaises(LedgerValidationError):
            validate_run(changed)

    def test_t212_order_mutation_is_rejected(self):
        record = sample_run(
            workspace="t212-demo",
            safety={
                "environment": "DEMO",
                "live_trading": False,
                "order_mutation": True,
            },
        )
        with self.assertRaises(LedgerValidationError):
            validate_run(record)

    def test_stale_running_worker_is_detected(self):
        record = sample_run(
            status="RUNNING",
            ended_at=None,
            heartbeat_at="2026-09-30T22:00:00Z",
        )
        now = datetime(2026, 9, 30, 22, 20, tzinfo=timezone.utc)
        self.assertEqual(health_status(record, now, stale_after_seconds=900), "STALE")

    def test_fresh_running_worker_is_running(self):
        now = datetime(2026, 9, 30, 22, 10, tzinfo=timezone.utc)
        record = sample_run(status="RUNNING", ended_at=None, heartbeat_at=now.isoformat())
        self.assertEqual(health_status(record, now), "RUNNING")

    def test_latest_record_selected_per_workspace_workflow(self):
        older = sample_run(run_id="run-older")
        newer = sample_run(
            run_id="run-newer",
            started_at="2026-09-30T23:00:00Z",
            ended_at="2026-09-30T23:01:00Z",
            heartbeat_at="2026-09-30T23:01:00Z",
        )
        latest = latest_by_workflow([newer, older])
        self.assertEqual(
            latest[("apps-plugins-bots", "connector-health")]["run_id"],
            "run-newer",
        )


if __name__ == "__main__":
    unittest.main()

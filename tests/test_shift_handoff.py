import unittest

from openwebui.tools.shift_handoff import build_handoff, render_markdown


def run_record(
    run_id="run-001",
    workspace="apps-plugins-bots",
    workflow="config-test",
    started_at="2026-09-30T22:00:00Z",
    status="SUCCEEDED",
    ended_at="2026-09-30T22:01:00Z",
    heartbeat_at="2026-09-30T22:01:00Z",
    evidence=None,
    output_refs=None,
    error=None,
    approvals=None,
    next_action="Continue branch-side validation.",
    safety=None,
):
    if workspace == "t212-demo" and safety is None:
        safety = {
            "environment": "DEMO",
            "live_trading": False,
            "order_mutation": False,
        }
    return {
        "run_id": run_id,
        "workspace": workspace,
        "workflow": workflow,
        "started_at": started_at,
        "ended_at": ended_at,
        "heartbeat_at": heartbeat_at,
        "status": status,
        "attempt": 1,
        "input_refs": [],
        "output_refs": output_refs or ["artifact.json"],
        "evidence": evidence or ["tests passed"],
        "model_role": None,
        "tool_ids": ["github"],
        "cost": {"currency": "NONE", "estimated": 0, "actual": 0},
        "error": error,
        "approvals": approvals or [],
        "next_action": next_action,
        "safety": safety,
    }


class ShiftHandoffTests(unittest.TestCase):
    def test_filters_to_workspace_and_period(self):
        records = [
            run_record(run_id="wanted"),
            run_record(run_id="other", workspace="books-publishing"),
            run_record(
                run_id="late",
                started_at="2026-10-01T02:00:00Z",
                ended_at="2026-10-01T02:01:00Z",
                heartbeat_at="2026-10-01T02:01:00Z",
            ),
        ]
        handoff = build_handoff(
            records,
            "apps-plugins-bots",
            "EVENING",
            "2026-09-30T20:00:00Z",
            "2026-09-30T23:00:00Z",
        )
        self.assertEqual(handoff["run_counts"]["total"], 1)
        self.assertEqual(handoff["run_counts"]["succeeded"], 1)

    def test_empty_period_does_not_claim_progress(self):
        handoff = build_handoff(
            [],
            "books-publishing",
            "MORNING",
            "2026-09-30T20:00:00Z",
            "2026-09-30T23:00:00Z",
        )
        self.assertIn("No verified automation runs", handoff["executive_summary"])
        self.assertEqual(handoff["completed"], [])

    def test_failed_run_becomes_blocker_with_smallest_action(self):
        record = run_record(
            status="FAILED",
            ended_at="2026-09-30T22:02:00Z",
            error={
                "category": "configuration",
                "summary": "Vision binding is absent.",
                "retryable": False,
            },
            next_action="Add an approved server-side vision model binding.",
        )
        handoff = build_handoff(
            [record],
            "apps-plugins-bots",
            "EVENT",
            "2026-09-30T20:00:00Z",
            "2026-09-30T23:00:00Z",
        )
        self.assertEqual(handoff["blockers"][0]["summary"], "Vision binding is absent.")
        self.assertIn("approved server-side", handoff["blockers"][0]["smallest_action"])

    def test_pending_approval_is_preserved(self):
        record = run_record(
            approvals=[
                {
                    "action": "deploy model router",
                    "state": "PENDING",
                    "approver_ref": "Katie",
                }
            ]
        )
        handoff = build_handoff(
            [record],
            "apps-plugins-bots",
            "EVENING",
            "2026-09-30T20:00:00Z",
            "2026-09-30T23:00:00Z",
        )
        self.assertEqual(handoff["approvals_required"][0]["state"], "PENDING")

    def test_t212_handoff_is_demo_only(self):
        record = run_record(workspace="t212-demo")
        handoff = build_handoff(
            [record],
            "t212-demo",
            "MORNING",
            "2026-09-30T20:00:00Z",
            "2026-09-30T23:00:00Z",
        )
        self.assertEqual(handoff["safety"]["environment"], "DEMO")
        self.assertFalse(handoff["safety"]["live_trading"])
        self.assertFalse(handoff["safety"]["order_mutation"])

    def test_stale_worker_is_counted(self):
        record = run_record(
            status="RUNNING",
            ended_at=None,
            heartbeat_at="2026-09-30T22:00:00Z",
        )
        handoff = build_handoff(
            [record],
            "apps-plugins-bots",
            "EVENING",
            "2026-09-30T20:00:00Z",
            "2026-09-30T23:00:00Z",
        )
        self.assertEqual(handoff["run_counts"]["stale"], 1)
        self.assertIn("STALE", handoff["current_state"][0])

    def test_markdown_includes_t212_safety_banner(self):
        handoff = build_handoff(
            [run_record(workspace="t212-demo")],
            "t212-demo",
            "MORNING",
            "2026-09-30T20:00:00Z",
            "2026-09-30T23:00:00Z",
        )
        rendered = render_markdown(handoff)
        self.assertIn("Trading 212 DEMO only", rendered)
        self.assertIn("LIVE trading disabled", rendered)
        self.assertIn("Order mutation disabled", rendered)


if __name__ == "__main__":
    unittest.main()

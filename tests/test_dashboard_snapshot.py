import unittest

from openwebui.tools.dashboard_snapshot import build_dashboard


def handoff(
    workspace="apps-plugins-bots",
    generated_at="2026-10-01T01:00:00Z",
    failed=0,
    blocked=0,
    running=0,
    stale=0,
    blockers=None,
    approvals=None,
):
    return {
        "handoff_id": f"{workspace}:test",
        "workspace": workspace,
        "cadence": "EVENT",
        "generated_at": generated_at,
        "period_start": "2026-10-01T00:00:00Z",
        "period_end": generated_at,
        "executive_summary": "Verified handoff.",
        "run_counts": {
            "total": 1,
            "succeeded": 1 if not failed and not blocked else 0,
            "failed": failed,
            "blocked": blocked,
            "running": running,
            "stale": stale,
        },
        "completed": [],
        "evidence": [],
        "current_state": [],
        "blockers": blockers or [],
        "approvals_required": approvals or [],
        "next_actions": [],
        "artifacts": ["artifact.json"],
        "rollback": None,
        "safety": (
            {"environment": "DEMO", "live_trading": False, "order_mutation": False}
            if workspace == "t212-demo"
            else None
        ),
    }


def run_record():
    return {
        "run_id": "run-cost-001",
        "workspace": "apps-plugins-bots",
        "workflow": "model-check",
        "started_at": "2026-10-01T00:00:00Z",
        "ended_at": "2026-10-01T00:01:00Z",
        "heartbeat_at": "2026-10-01T00:01:00Z",
        "status": "SUCCEEDED",
        "attempt": 1,
        "input_refs": [],
        "output_refs": [],
        "evidence": ["verified"],
        "approvals": [],
        "next_action": None,
        "cost": {"currency": "CREDITS", "estimated": 90, "actual": 100},
        "safety": None,
    }


class DashboardSnapshotTests(unittest.TestCase):
    def test_four_workspace_panels_always_exist(self):
        dashboard = build_dashboard([], generated_at="2026-10-01T02:00:00Z")
        self.assertEqual(len(dashboard["workspaces"]), 4)
        self.assertEqual(dashboard["overall_status"], "NO_DATA")

    def test_latest_handoff_wins(self):
        old = handoff(generated_at="2026-10-01T00:30:00Z")
        new = handoff(generated_at="2026-10-01T01:30:00Z")
        new["executive_summary"] = "Latest verified state."
        dashboard = build_dashboard([new, old], generated_at="2026-10-01T02:00:00Z")
        panel = dashboard["workspaces"]["apps-plugins-bots"]
        self.assertEqual(panel["summary"], "Latest verified state.")
        self.assertEqual(panel["last_handoff_at"], "2026-10-01T01:30:00Z")

    def test_failure_or_stale_worker_degrades_dashboard(self):
        dashboard = build_dashboard(
            [handoff(failed=1, stale=1)],
            generated_at="2026-10-01T02:00:00Z",
        )
        self.assertEqual(dashboard["overall_status"], "DEGRADED")
        self.assertEqual(
            dashboard["workspaces"]["apps-plugins-bots"]["status"],
            "DEGRADED",
        )

    def test_pending_approval_is_attention_not_success(self):
        approval = {
            "action": "deploy staged control plane",
            "state": "PENDING",
            "approver_ref": "Katie",
        }
        dashboard = build_dashboard(
            [handoff(approvals=[approval])],
            generated_at="2026-10-01T02:00:00Z",
        )
        panel = dashboard["workspaces"]["apps-plugins-bots"]
        self.assertEqual(panel["status"], "ATTENTION")
        self.assertEqual(len(panel["pending_approvals"]), 1)

    def test_actual_costs_are_aggregated_by_unit(self):
        dashboard = build_dashboard(
            [handoff()],
            [run_record(), run_record()],
            generated_at="2026-10-01T02:00:00Z",
        )
        self.assertEqual(dashboard["costs_by_unit"]["CREDITS"], 200.0)

    def test_unsafe_t212_handoff_is_rejected(self):
        unsafe = handoff(workspace="t212-demo")
        unsafe["safety"]["live_trading"] = True
        with self.assertRaises(ValueError):
            build_dashboard([unsafe], generated_at="2026-10-01T02:00:00Z")

    def test_dashboard_always_exposes_demo_only_t212_state(self):
        dashboard = build_dashboard(
            [handoff(workspace="t212-demo")],
            generated_at="2026-10-01T02:00:00Z",
        )
        self.assertEqual(dashboard["t212_safety"]["environment"], "DEMO")
        self.assertFalse(dashboard["t212_safety"]["live_trading"])
        self.assertFalse(dashboard["t212_safety"]["order_mutation"])


if __name__ == "__main__":
    unittest.main()

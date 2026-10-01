"""Build one read-only dashboard snapshot from handoffs and ledger records."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from openwebui.tools.automation_ledger import validate_run


WORKSPACE_ORDER = [
    "t212-demo",
    "apps-plugins-bots",
    "you-heal-content",
    "books-publishing",
]
STATUS_RANK = {"NO_DATA": 0, "HEALTHY": 1, "ATTENTION": 2, "DEGRADED": 3}


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("dashboard inputs require timezone-aware timestamps")
    return parsed.astimezone(timezone.utc)


def _panel_status(handoff: Mapping[str, Any]) -> str:
    counts = handoff.get("run_counts", {})
    if counts.get("failed", 0) or counts.get("stale", 0):
        return "DEGRADED"
    pending = [
        item for item in handoff.get("approvals_required", [])
        if item.get("state") == "PENDING"
    ]
    if counts.get("blocked", 0) or handoff.get("blockers") or pending:
        return "ATTENTION"
    return "HEALTHY"


def _validate_handoff(handoff: Mapping[str, Any]) -> None:
    required = {
        "workspace",
        "generated_at",
        "executive_summary",
        "run_counts",
        "blockers",
        "approvals_required",
        "next_actions",
        "artifacts",
    }
    missing = required - set(handoff)
    if missing:
        raise ValueError(f"handoff missing fields: {sorted(missing)}")
    if handoff["workspace"] not in WORKSPACE_ORDER:
        raise ValueError("unknown handoff workspace")
    _time(handoff["generated_at"])
    if handoff["workspace"] == "t212-demo":
        safety = handoff.get("safety") or {}
        if (
            safety.get("environment") != "DEMO"
            or safety.get("live_trading") is not False
            or safety.get("order_mutation") is not False
        ):
            raise ValueError("T212 handoff violates dashboard safety invariant")


def build_dashboard(
    handoffs: Iterable[Mapping[str, Any]],
    runs: Iterable[Mapping[str, Any]] = (),
    generated_at: str | None = None,
) -> dict[str, Any]:
    latest: dict[str, Mapping[str, Any]] = {}
    for handoff in handoffs:
        _validate_handoff(handoff)
        workspace = handoff["workspace"]
        current = latest.get(workspace)
        if current is None or _time(handoff["generated_at"]) > _time(current["generated_at"]):
            latest[workspace] = handoff

    panels: dict[str, dict[str, Any]] = {}
    totals = {
        "verified_runs": 0,
        "failed": 0,
        "blocked": 0,
        "running": 0,
        "stale": 0,
        "pending_approvals": 0,
    }
    for workspace in WORKSPACE_ORDER:
        handoff = latest.get(workspace)
        if handoff is None:
            panels[workspace] = {
                "status": "NO_DATA",
                "summary": "No verified handoff is available.",
                "run_counts": {},
                "blockers": [],
                "pending_approvals": [],
                "next_actions": [],
                "artifacts": [],
                "last_handoff_at": None,
            }
            continue

        counts = dict(handoff["run_counts"])
        pending = [
            item for item in handoff["approvals_required"]
            if item.get("state") == "PENDING"
        ]
        panels[workspace] = {
            "status": _panel_status(handoff),
            "summary": handoff["executive_summary"],
            "run_counts": counts,
            "blockers": list(handoff["blockers"]),
            "pending_approvals": pending,
            "next_actions": list(handoff["next_actions"]),
            "artifacts": list(handoff["artifacts"]),
            "last_handoff_at": handoff["generated_at"],
        }
        totals["verified_runs"] += counts.get("total", 0)
        for key in ("failed", "blocked", "running", "stale"):
            totals[key] += counts.get(key, 0)
        totals["pending_approvals"] += len(pending)

    costs: dict[str, float] = {}
    for record in runs:
        validate_run(record)
        cost = record.get("cost") or {}
        amount = cost.get("actual")
        unit = cost.get("currency")
        if amount is not None and unit and unit != "NONE":
            costs[unit] = costs.get(unit, 0.0) + float(amount)

    statuses = [panel["status"] for panel in panels.values()]
    if all(status == "NO_DATA" for status in statuses):
        overall = "NO_DATA"
    else:
        overall = max(statuses, key=lambda status: STATUS_RANK[status])
        if overall == "NO_DATA":
            overall = "HEALTHY"

    timestamp = generated_at or datetime.now(timezone.utc).isoformat()
    _time(timestamp)
    return {
        "generated_at": timestamp,
        "overall_status": overall,
        "workspace_order": list(WORKSPACE_ORDER),
        "workspaces": panels,
        "totals": totals,
        "costs_by_unit": dict(sorted(costs.items())),
        "t212_safety": {
            "environment": "DEMO",
            "live_trading": False,
            "order_mutation": False,
        },
    }

"""Deterministic morning/evening handoffs built from validated ledger records."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from openwebui.tools.automation_ledger import health_status, validate_run


WORKSPACES = {
    "t212-demo",
    "apps-plugins-bots",
    "you-heal-content",
    "books-publishing",
}
CADENCES = {"MORNING", "EVENING", "EVENT"}


def _utc(value: str | datetime) -> datetime:
    parsed = (
        value
        if isinstance(value, datetime)
        else datetime.fromisoformat(value.replace("Z", "+00:00"))
    )
    if parsed.tzinfo is None:
        raise ValueError("handoff timestamps must include a timezone")
    return parsed.astimezone(timezone.utc)


def _unique(items: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))


def build_handoff(
    records: Iterable[Mapping[str, Any]],
    workspace: str,
    cadence: str,
    period_start: str | datetime,
    period_end: str | datetime,
) -> dict[str, Any]:
    if workspace not in WORKSPACES:
        raise ValueError("unknown workspace")
    if cadence not in CADENCES:
        raise ValueError("unknown cadence")
    start = _utc(period_start)
    end = _utc(period_end)
    if end < start:
        raise ValueError("period_end cannot precede period_start")

    selected: list[Mapping[str, Any]] = []
    for record in records:
        validate_run(record)
        when = _utc(record["started_at"])
        if record["workspace"] == workspace and start <= when <= end:
            selected.append(record)
    selected.sort(key=lambda item: _utc(item["started_at"]))

    counts = {
        "total": len(selected),
        "succeeded": sum(item["status"] == "SUCCEEDED" for item in selected),
        "failed": sum(item["status"] == "FAILED" for item in selected),
        "blocked": sum(item["status"] == "BLOCKED" for item in selected),
        "running": sum(item["status"] == "RUNNING" for item in selected),
        "stale": sum(
            health_status(item, now=end) == "STALE"
            for item in selected
            if item["status"] == "RUNNING"
        ),
    }

    completed = [
        f'{item["workflow"]}: {", ".join(item.get("output_refs", [])) or "completed"}'
        for item in selected
        if item["status"] == "SUCCEEDED"
    ]
    evidence = _unique(
        evidence
        for item in selected
        for evidence in item.get("evidence", [])
    )
    current_state = [
        f'{item["workflow"]}: {health_status(item, now=end)}'
        for item in selected
        if item["status"] == "RUNNING"
    ]
    blockers = [
        {
            "summary": (
                item.get("error", {}).get("summary")
                if item.get("error")
                else f'{item["workflow"]} is {item["status"].lower()}'
            ),
            "owner": "SYSTEM",
            "smallest_action": item.get("next_action") or "Inspect run evidence.",
        }
        for item in selected
        if item["status"] in {"FAILED", "BLOCKED"}
    ]

    approvals: list[dict[str, Any]] = []
    for item in selected:
        for approval in item.get("approvals", []):
            if approval.get("state") in {"PENDING", "APPROVED", "REJECTED"}:
                approvals.append(
                    {
                        "action": approval["action"],
                        "state": approval["state"],
                        "approver_ref": approval.get("approver_ref"),
                    }
                )

    next_actions = [
        {
            "action": item["next_action"],
            "owner": "SYSTEM",
            "priority": "P1" if item["status"] in {"FAILED", "BLOCKED"} else "P2",
        }
        for item in selected
        if item.get("next_action")
    ]
    artifacts = _unique(
        artifact
        for item in selected
        for artifact in item.get("output_refs", [])
    )

    if not selected:
        summary = "No verified automation runs were recorded for this period."
    else:
        summary = (
            f'{counts["succeeded"]}/{counts["total"]} runs succeeded; '
            f'{counts["failed"]} failed, {counts["blocked"]} blocked, '
            f'{counts["running"]} running, {counts["stale"]} stale.'
        )

    generated = end.isoformat().replace("+00:00", "Z")
    handoff: dict[str, Any] = {
        "handoff_id": f'{workspace}:{cadence.lower()}:{generated}',
        "workspace": workspace,
        "cadence": cadence,
        "generated_at": generated,
        "period_start": start.isoformat().replace("+00:00", "Z"),
        "period_end": generated,
        "executive_summary": summary,
        "run_counts": counts,
        "completed": completed,
        "evidence": evidence,
        "current_state": current_state,
        "blockers": blockers,
        "approvals_required": approvals,
        "next_actions": next_actions,
        "artifacts": artifacts,
        "rollback": "Use the rollback reference recorded by each contributing run.",
        "safety": None,
    }
    if workspace == "t212-demo":
        handoff["safety"] = {
            "environment": "DEMO",
            "live_trading": False,
            "order_mutation": False,
        }
    return handoff


def render_markdown(handoff: Mapping[str, Any]) -> str:
    lines = [
        f'# {handoff["workspace"]} — {handoff["cadence"].title()} handoff',
        "",
        handoff["executive_summary"],
    ]
    for heading, key in (
        ("Completed", "completed"),
        ("Evidence", "evidence"),
        ("Current state", "current_state"),
        ("Artifacts", "artifacts"),
    ):
        lines.extend(["", f"## {heading}", ""])
        values = handoff.get(key, [])
        lines.extend(f"- {value}" for value in values)
        if not values:
            lines.append("- None recorded.")

    lines.extend(["", "## Blockers", ""])
    blockers = handoff.get("blockers", [])
    lines.extend(
        f'- {item["summary"]} — {item["owner"]}: {item["smallest_action"]}'
        for item in blockers
    )
    if not blockers:
        lines.append("- None recorded.")

    lines.extend(["", "## Approvals", ""])
    approvals = handoff.get("approvals_required", [])
    lines.extend(f'- {item["action"]}: {item["state"]}' for item in approvals)
    if not approvals:
        lines.append("- None required.")

    lines.extend(["", "## Next actions", ""])
    actions = handoff.get("next_actions", [])
    lines.extend(
        f'- [{item["priority"]}] {item["owner"]}: {item["action"]}'
        for item in actions
    )
    if not actions:
        lines.append("- None recorded.")

    if handoff["workspace"] == "t212-demo":
        lines.extend(
            [
                "",
                "## Safety",
                "",
                "- Trading 212 DEMO only",
                "- LIVE trading disabled",
                "- Order mutation disabled",
            ]
        )
    return "\n".join(lines) + "\n"

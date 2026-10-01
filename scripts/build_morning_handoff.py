#!/usr/bin/env python3
"""Generate a compact, evidence-backed morning human-action pack."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "webui-control" / "morning-human-actions.json"
MANIFEST_PATH = ROOT / "webui-control" / "release-manifest.json"
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")

COMPONENT_LABELS = {
    "workspace-registry": "four-workspace registry",
    "agent-contract": "shared agent safety contract",
    "model-router": "model and vision router",
    "plugin-registry": "least-privilege connector registry",
    "automation-ledger": "durable automation ledger",
    "shift-handoff": "verified shift handoff",
    "books-pipeline": "Books workflow gates",
    "you-heal-pipeline": "You Heal workflow gates",
    "dashboard-snapshot": "executive dashboard data layer",
    "credit-control": "observe-only credit control",
    "server-deployment-preflight": "server backup/deployment preflight",
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def git_value(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, text=True, capture_output=True, check=False
    )
    if result.returncode != 0:
        raise RuntimeError(f"Git command failed: {' '.join(args)}")
    return result.stdout.strip()


def run_repository_preflight() -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_webui_control.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Repository preflight did not return JSON.") from exc
    if result.returncode != 0 or report.get("status") != "PASS":
        report["status"] = "FAIL"
    return report


def validate_config(config: dict[str, Any]) -> None:
    actions = config.get("actions")
    if not isinstance(actions, list) or not actions:
        raise ValueError("At least one human action is required.")
    priorities = []
    for action in actions:
        priorities.append(action.get("priority"))
        if action.get("requirement") not in {"REQUIRED", "OPTIONAL"}:
            raise ValueError(f"Invalid action requirement: {action.get('id')}")
        if not action.get("device_window") or not action.get("success"):
            raise ValueError(f"Incomplete action: {action.get('id')}")
        if "{commit}" not in (action.get("command_template") or "") and action.get("id") in {
            "server_sync_and_readiness",
            "deployment_approval",
        }:
            raise ValueError(f"Commit pin missing: {action.get('id')}")
        if not action.get("never_paste"):
            raise ValueError(f"Secret warning missing: {action.get('id')}")
    if priorities != sorted(priorities) or len(set(priorities)) != len(priorities):
        raise ValueError("Action priorities must be unique and ascending.")

    boundaries = config.get("global_boundaries", {})
    if (
        boundaries.get("t212_environment") != "DEMO"
        or boundaries.get("live_trading_enabled") is not False
        or boundaries.get("order_mutation_enabled") is not False
        or boundaries.get("publishing_enabled") is not False
        or boundaries.get("scheduling_enabled") is not False
        or boundaries.get("automatic_spending_enabled") is not False
    ):
        raise ValueError("Human-action pack violates safety boundaries.")


def render_pack(
    config: dict[str, Any],
    manifest: dict[str, Any],
    preflight: dict[str, Any],
    *,
    commit: str,
    branch: str,
    server_report: dict[str, Any] | None = None,
) -> str:
    if not SHA_PATTERN.fullmatch(commit):
        raise ValueError("A full 40-character commit SHA is required.")
    validate_config(config)

    components = [
        COMPONENT_LABELS.get(item.get("id"), item.get("id", "unknown component"))
        for item in manifest.get("components", [])
    ]
    server_status = server_report.get("status") if server_report else "NOT_RUN"
    server_note = (
        f"{server_status}; failed checks: {', '.join(server_report.get('failed_checks', [])) or 'none'}"
        if server_report
        else "NOT_RUN — requires the authenticated Contabo SSH session"
    )

    lines = [
        f"# {config['title']}",
        "",
        "## Completed",
        "",
        f"- Staged exact branch commit: `{commit}` on `{branch}`.",
        f"- Added and verified: {', '.join(components)}.",
        "- No live WebUI deployment, publishing, spending or trading mutation occurred.",
        "",
        "## Test status",
        "",
        f"- Repository: **{preflight.get('status', 'UNKNOWN')}** — {preflight.get('tests_run', 0)} tests, "
        f"{len(preflight.get('configs_checked', []))} configs, "
        f"{len(preflight.get('components_checked', []))} components.",
        f"- Failures: {', '.join(preflight.get('failures', [])) or 'none'}.",
        f"- Server: **{server_note}**.",
        "- T212: **DEMO only; LIVE disabled; order mutation disabled**.",
        "",
        "## Human-only actions",
        "",
    ]

    for action in config["actions"]:
        lines.extend(
            [
                f"### {action['priority']}. {action['requirement']} — {action['id'].replace('_', ' ')}",
                "",
                f"- **When:** {action['condition']}",
                f"- **Where:** {action['device_window']}",
            ]
        )
        if action.get("command_template"):
            command = action["command_template"].format(commit=commit)
            lines.extend(["- **Do:**", "", "  ```text", f"  {command}", "  ```"])
        elif action.get("click_path"):
            lines.append(f"- **Do:** {action['click_path']}")
        lines.extend(
            [
                f"- **Success:** {action['success']}",
                f"- **If it fails:** {action['failure']}",
                f"- **Never paste/share:** {', '.join(action['never_paste'])}.",
                f"- **Then resumes:** {action['automatic_resume']}",
                "",
            ]
        )

    return "\n".join(lines).rstrip() + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server-report", type=Path, help="Optional JSON from server_deployment_preflight.py.")
    parser.add_argument("--output", type=Path, help="Optional Markdown output path.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = load_json(CONFIG_PATH)
    manifest = load_json(MANIFEST_PATH)
    branch = git_value("rev-parse", "--abbrev-ref", "HEAD")
    commit = git_value("rev-parse", "HEAD")
    preflight = run_repository_preflight()
    server_report = load_json(args.server_report) if args.server_report else None
    rendered = render_pack(
        config,
        manifest,
        preflight,
        commit=commit,
        branch=branch,
        server_report=server_report,
    )
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0 if preflight.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

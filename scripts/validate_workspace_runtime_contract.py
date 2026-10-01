#!/usr/bin/env python3
"""Validate logical workspace roles against explicit runtime bindings.

This is repository-only validation. It proves mapping consistency, not that the
OpenWebUI runtime currently has the required models/skills/tools attached.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def load(relative: str) -> dict[str, Any]:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def validate() -> dict[str, Any]:
    workspaces = load("webui-control/workspaces.json")
    contract = load("webui-control/workspace-runtime-contract.json")
    runtime = contract.get("workspaces") or {}
    failures = []
    checked = []

    for workspace in workspaces.get("workspaces", []):
        workspace_id = workspace.get("id")
        mapped = runtime.get(workspace_id)
        if not mapped:
            failures.append(f"{workspace_id}: no runtime contract")
            continue
        if not mapped.get("model_id"):
            failures.append(f"{workspace_id}: model_id missing")

        logical = mapped.get("logical_roles") or {}
        for role in workspace.get("agents", []):
            binding = logical.get(role)
            if not binding:
                failures.append(f"{workspace_id}/{role}: no runtime binding")
                continue
            skills = binding.get("skills") or []
            tools = binding.get("tools") or []
            code_refs = binding.get("code") or []
            if not skills and not tools and not code_refs:
                failures.append(f"{workspace_id}/{role}: empty runtime binding")
            for ref in code_refs:
                if not (ROOT / ref).is_file():
                    failures.append(f"{workspace_id}/{role}: missing code {ref}")
            checked.append({
                "workspace": workspace_id,
                "logical_role": role,
                "model_id": mapped.get("model_id"),
                "skills": skills,
                "tools": tools,
                "code": code_refs,
            })

        extras = sorted(set(logical) - set(workspace.get("agents", [])))
        if extras:
            failures.append(f"{workspace_id}: runtime contract has undeclared roles {extras}")

    return {
        "status": "PASS" if not failures else "FAIL",
        "logical_roles_checked": len(checked),
        "failures": failures,
        "bindings": checked,
        "runtime_proof": False,
    }


def main() -> int:
    result = validate()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

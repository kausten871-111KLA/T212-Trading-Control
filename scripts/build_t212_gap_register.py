#!/usr/bin/env python3
"""Build a requirement-level T212 implementation and lost-methodology register.

This script is read-only. It distinguishes repository implementation from
runtime proof and never infers deployment from configuration alone.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def load(path: Path, default: Any):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def runtime_index(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("id")): row
        for row in payload.get("components", [])
        if isinstance(row, dict) and row.get("id")
    }


def classify(req: dict[str, Any], runtime: dict[str, dict[str, Any]]) -> tuple[str, list[str]]:
    config_refs = req.get("config_refs") or []
    code_refs = req.get("code_refs") or []
    missing = [ref for ref in config_refs + code_refs if not (ROOT / ref).is_file()]
    if missing:
        return "MISSING", [f"missing repository artifact: {ref}" for ref in missing]

    runtime_keys = req.get("runtime_evidence_keys") or []
    if not runtime_keys:
        return "BUILT_UNPROVEN", ["repository implementation exists; no runtime evidence mapping defined"]

    rows = [runtime.get(key) for key in runtime_keys]
    if any(row is None for row in rows):
        return "BUILT_UNPROVEN", ["required runtime evidence not collected"]

    blockers = [str(row.get("blocker")) for row in rows if row and row.get("blocker")]
    if blockers:
        return "BLOCKED", blockers

    if all(
        row
        and row.get("deployed") is True
        and row.get("running") is True
        and (row.get("evidence") or [])
        for row in rows
    ):
        return "PROVEN", [str(item) for row in rows for item in (row.get("evidence") or [])]

    if any(row and (row.get("deployed") is True or row.get("running") is True) for row in rows):
        return "PARTIAL", [str(item) for row in rows if row for item in (row.get("evidence") or [])]

    return "BUILT_UNPROVEN", ["runtime evidence exists but does not prove active operation"]


def build(runtime_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    mapping = load(ROOT / "webui-control" / "t212-implementation-map.json", {})
    runtime = runtime_index(runtime_payload or {})
    rows = []

    for req in mapping.get("requirements", []):
        status, evidence = classify(req, runtime)
        rows.append({
            "id": req.get("id"),
            "requirement": req.get("requirement"),
            "status": status,
            "config_refs": req.get("config_refs") or [],
            "code_refs": req.get("code_refs") or [],
            "runtime_evidence": evidence,
            "known_gap": req.get("known_gap"),
            "next_action": (
                req.get("known_gap")
                if status != "PROVEN"
                else "retain evidence and monitor for regression"
            ),
        })

    counts = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "workspace": "t212-demo",
        "principle": "configuration or prompt presence is not operational proof",
        "counts": counts,
        "requirements": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-evidence", help="Optional runtime evidence JSON.")
    parser.add_argument("--output", help="Optional output JSON.")
    args = parser.parse_args()

    runtime = load(Path(args.runtime_evidence), {}) if args.runtime_evidence else None
    result = build(runtime)
    encoded = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

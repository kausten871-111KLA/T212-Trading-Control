#!/usr/bin/env python3
"""Build an evidence-based implementation register for the WebUI control plane.

Repository presence proves only that something is built. Deployment/running
states require an explicit evidence file produced by server inspection.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VALID_STATUSES = {"PROVEN", "BUILT_UNPROVEN", "PARTIAL", "MISSING", "BLOCKED"}


def load_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def evidence_index(payload: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, dict):
        return {}
    rows = payload.get("components")
    if not isinstance(rows, list):
        return {}
    return {
        str(row.get("id")): row
        for row in rows
        if isinstance(row, dict) and row.get("id")
    }


def classify(component: dict[str, Any], evidence: dict[str, Any] | None) -> tuple[str, list[str]]:
    missing: list[str] = []
    for key in ("config", "code"):
        relative = component.get(key)
        if relative and not (ROOT / relative).is_file():
            missing.append(relative)
    if missing:
        return "MISSING", [f"missing:{item}" for item in missing]

    if not evidence:
        return "BUILT_UNPROVEN", ["no server/runtime evidence"]

    blocker = str(evidence.get("blocker") or "").strip()
    if blocker:
        return "BLOCKED", [blocker]

    deployed = evidence.get("deployed") is True
    running = evidence.get("running") is True
    callable_ok = evidence.get("callable") is True
    refs = evidence.get("evidence") if isinstance(evidence.get("evidence"), list) else []

    if deployed and running and callable_ok and refs:
        return "PROVEN", [str(item) for item in refs]
    if deployed or running or callable_ok:
        return "PARTIAL", [str(item) for item in refs] or ["some runtime evidence, end-to-end proof incomplete"]
    return "BUILT_UNPROVEN", [str(item) for item in refs] or ["runtime evidence does not prove deployment"]


def build_register(evidence_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    manifest = load_json(ROOT / "webui-control" / "release-manifest.json", {})
    evidence = evidence_index(evidence_payload)
    rows: list[dict[str, Any]] = []

    for component in manifest.get("components", []):
        component_id = str(component.get("id") or "")
        status, notes = classify(component, evidence.get(component_id))
        ev = evidence.get(component_id) or {}
        rows.append(
            {
                "id": component_id,
                "status": status,
                "config": component.get("config"),
                "code": component.get("code"),
                "deployed": ev.get("deployed") is True,
                "running": ev.get("running") is True,
                "callable": ev.get("callable") is True,
                "last_verified": ev.get("last_verified"),
                "evidence": notes,
                "next_action": ev.get("next_action")
                or (
                    "collect server/OpenWebUI runtime evidence"
                    if status == "BUILT_UNPROVEN"
                    else "resolve missing repository component"
                    if status == "MISSING"
                    else "complete end-to-end proof"
                    if status == "PARTIAL"
                    else "resolve blocker"
                    if status == "BLOCKED"
                    else "monitor"
                ),
            }
        )

    counts = {status: 0 for status in sorted(VALID_STATUSES)}
    for row in rows:
        counts[row["status"]] += 1

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "release_state": manifest.get("release_state"),
        "live_effect": manifest.get("live_effect"),
        "counts": counts,
        "components": rows,
        "evidence_source": "explicit runtime evidence" if evidence else "none",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", help="Optional server/runtime evidence JSON.")
    parser.add_argument("--output", help="Optional output JSON path.")
    args = parser.parse_args()

    evidence_payload = load_json(Path(args.evidence), {}) if args.evidence else None
    result = build_register(evidence_payload)
    encoded = json.dumps(result, indent=2, sort_keys=True)

    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

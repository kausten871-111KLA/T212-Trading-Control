#!/usr/bin/env python3
"""Build progress for the controlled 20-DEMO validation programme.

Read-only. Counts only complete, broker-verified records and never submits or
modifies an order.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REQUIRED = {
    "candidate_source",
    "catalyst_or_cause_confidence",
    "qualification_gates",
    "ordinary_ticker",
    "t212_ticker",
    "exposure",
    "quantity",
    "broker_response",
    "fill_verification",
    "exit_reason",
    "closure_verification",
    "realised_result",
    "failure_or_rejection_code",
    "learning_item",
}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def assess(row: dict[str, Any]) -> dict[str, Any]:
    missing = sorted(key for key in REQUIRED if key not in row)
    safety = row.get("safety") or {}
    broker_verified = (
        row.get("fill_verification") is True
        and row.get("closure_verification") is True
    )
    safe = (
        safety.get("environment") == "DEMO"
        and safety.get("live_trading") is False
    )
    valid = not missing and broker_verified and safe
    return {
        "record_id": row.get("record_id") or row.get("proposal_id"),
        "valid": valid,
        "missing_fields": missing,
        "broker_verified": broker_verified,
        "demo_safe": safe,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--target", type=int, default=20)
    args = parser.parse_args()

    rows = read_jsonl(Path(args.ledger))
    assessments = [assess(row) for row in rows]
    complete = [row for row in assessments if row["valid"]]
    invalid = [row for row in assessments if not row["valid"]]
    target = max(1, int(args.target))
    payload = {
        "programme": "20_DEMO_TRADES",
        "target": target,
        "complete_verified": len(complete),
        "remaining": max(0, target - len(complete)),
        "record_count": len(rows),
        "invalid_or_incomplete_count": len(invalid),
        "complete": len(complete) >= target,
        "order_actions": "none",
        "invalid_or_incomplete": invalid,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

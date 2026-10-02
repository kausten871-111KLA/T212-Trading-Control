#!/usr/bin/env python3
"""Build one no-network Trading Operations dashboard artifact from state files.

The command reads existing evidence only.  It never calls a provider, model or
broker and never submits an order.  Its only writes are the requested dashboard
file and, when explicitly supplied, one append-only automation-ledger record.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from openwebui.tools.trading_dashboard_evidence import build_trading_dashboard


DEFAULT_STATE = Path(os.getenv("T212_SCANNER_STATE_DIR", "/var/lib/t212-scanner"))
DEFAULT_BINDINGS = ROOT / "webui-control" / "t212-agent-bindings.json"


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _object(path: Path) -> dict[str, Any] | None:
    value = load_json(path, None)
    return value if isinstance(value, dict) else None


def _new_instruments(path: Path) -> dict[str, Any] | None:
    value = _object(path)
    if not value:
        return None
    return {
        "generated_at": value.get("generatedAt"),
        "environment": "DEMO",
        "live_trading_enabled": False,
        "orders_submitted": 0,
        "instruments": list(value.get("added") or []),
        "baseline_was_present": value.get("baselineWasPresent") is True,
    }


def _execution_evidence(path: Path) -> dict[str, Any] | None:
    value = load_json(path, None)
    if isinstance(value, dict):
        rows = value.get("broker_verified_fills") or []
        environment = value.get("environment")
        if environment not in (None, "DEMO"):
            raise ValueError("broker fill evidence is not DEMO")
    elif isinstance(value, list):
        # Legacy lists are accepted only row by row when explicitly verified.
        rows = [row for row in value if isinstance(row, dict) and row.get("broker_verified") is True]
    else:
        return None
    return {
        "environment": "DEMO",
        "live_trading_enabled": False,
        "orders_submitted": 0,
        "broker_verified_fills": list(rows),
    }


def build_from_state(
    state_dir: Path,
    *,
    bindings_path: Path = DEFAULT_BINDINGS,
    generated_at: str | None = None,
) -> dict[str, Any]:
    return build_trading_dashboard(
        market_snapshot=_object(state_dir / "market_snapshot.json"),
        scanner=_object(state_dir / "scanner_latest.json"),
        readiness=_object(state_dir / "candidate_readiness.json"),
        new_instruments=_new_instruments(state_dir / "t212_instrument_diff.json"),
        execution_evidence=_execution_evidence(state_dir / "broker_fills.json"),
        eod_audit=_object(state_dir / "eod_audit_latest.json"),
        agent_bindings=_object(bindings_path),
        generated_at=generated_at,
    )


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def ledger_record(dashboard: dict[str, Any], output: Path) -> dict[str, Any]:
    degraded = list(dashboard.get("degraded_evidence") or [])
    complete = dashboard.get("status") == "EVIDENCE_COMPLETE"
    timestamp = str(dashboard["generated_at"])
    return {
        "run_id": "trading-dashboard-" + timestamp.replace(":", "").replace("+", ""),
        "workspace": "t212-demo",
        "workflow": "trading-dashboard-evidence",
        "started_at": timestamp,
        "ended_at": timestamp,
        "heartbeat_at": timestamp,
        "status": "SUCCEEDED" if complete else "BLOCKED",
        "attempt": 1,
        "input_refs": [
            "market_snapshot.json", "scanner_latest.json", "candidate_readiness.json",
            "t212_instrument_diff.json", "broker_fills.json", "eod_audit_latest.json",
        ],
        "output_refs": [str(output)],
        "evidence": [
            f"dashboard_status={dashboard.get('status')}",
            f"degraded_evidence={','.join(degraded) or 'none'}",
            "environment=DEMO", "live_trading=false", "orders_submitted=0",
        ],
        "model_role": None,
        "tool_ids": [],
        "cost": {"currency": "NONE", "estimated": 0, "actual": 0},
        "error": None if complete else {
            "code": "DASHBOARD_EVIDENCE_INCOMPLETE",
            "summary": "Missing, stale or unverified dashboard evidence: " + ", ".join(degraded),
            "retryable": True,
        },
        "approvals": [],
        "next_action": (
            "Retain the evidence artifact; no order action is authorized by this dashboard."
            if complete else
            "Restore fresh verified evidence for: " + ", ".join(degraded)
        ),
        "safety": {"environment": "DEMO", "live_trading": False, "order_mutation": False},
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--bindings", type=Path, default=DEFAULT_BINDINGS)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, help="Optional append-only automation ledger.")
    parser.add_argument("--generated-at", help="Timezone-aware test/inspection timestamp.")
    parser.add_argument("--require-complete", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    dashboard = build_from_state(
        args.state_dir, bindings_path=args.bindings, generated_at=args.generated_at
    )
    atomic_json(args.output, dashboard)
    if args.ledger:
        from openwebui.tools.automation_ledger import append_run

        append_run(args.ledger, ledger_record(dashboard, args.output))
    print(json.dumps({
        "status": dashboard["status"],
        "degraded_evidence": dashboard["degraded_evidence"],
        "portfolio_state": dashboard["portfolio"]["state"],
        "orders_submitted": 0,
        "output": str(args.output),
    }, sort_keys=True))
    return 2 if args.require_complete and dashboard["status"] != "EVIDENCE_COMPLETE" else 0


if __name__ == "__main__":
    raise SystemExit(main())

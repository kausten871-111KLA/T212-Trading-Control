#!/usr/bin/env python3
"""End-of-day missed-green audit runner. Read-only; never submits orders."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from openwebui.tools.missed_green_audit import MissedGreenAudit

STATE = Path(os.getenv("T212_SCANNER_STATE_DIR", "/var/lib/t212-scanner"))
OUT = STATE / "eod_audit_latest.json"


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def atomic_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    actual = load_json(STATE / "actual_movers.json", [])
    surfaced = load_json(STATE / "surfaced_candidates.json", [])
    traded = load_json(STATE / "broker_fills.json", [])

    audit = MissedGreenAudit(top_n=100).classify(actual, surfaced, traded)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "environment": "DEMO",
        "actual_mover_count": len(actual) if isinstance(actual, list) else 0,
        "surfaced_count": len(surfaced) if isinstance(surfaced, list) else 0,
        "broker_fill_count": len(traded) if isinstance(traded, list) else 0,
        "audit": audit,
        "orders_submitted": 0,
        "live_trading_enabled": False,
    }
    atomic_json(OUT, payload)
    print(json.dumps({
        "ok": True,
        "environment": "DEMO",
        "audit_version": audit["auditVersion"],
        "counts": audit["counts"],
        "orders_submitted": 0,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

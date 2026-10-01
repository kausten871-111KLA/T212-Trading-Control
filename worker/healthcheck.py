#!/usr/bin/env python3
"""Read-only health evaluation for the persistent T212 DEMO discovery worker."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

STATE = Path(os.getenv("T212_SCANNER_STATE_DIR", "/var/lib/t212-scanner"))
STATUS = STATE / "status.json"
SCAN = STATE / "scanner_latest.json"
MAX_STATUS_AGE = int(os.getenv("T212_WORKER_MAX_STATUS_AGE_SECONDS", "900"))
MAX_SOURCE_AGE = int(os.getenv("T212_MARKET_MAX_AGE_SECONDS", "300"))
MAX_CACHE_AGE = int(os.getenv("T212_INSTRUMENT_CACHE_TTL_SECONDS", "86400"))


def load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def main() -> int:
    now = time.time()
    payload = load(STATUS)
    if not isinstance(payload, dict):
        print(json.dumps({"ok": False, "state": "NO_STATUS", "reason": "status unavailable"}))
        return 1

    status_age = max(0.0, now - STATUS.stat().st_mtime)
    reasons = []
    if status_age >= MAX_STATUS_AGE:
        reasons.append("STATUS_STALE")
    if payload.get("mode") != "DEMO":
        reasons.append("NOT_DEMO")
    if payload.get("live_trading_enabled") is not False:
        reasons.append("LIVE_NOT_DISABLED")
    if int(payload.get("orders_submitted", 0) or 0) != 0:
        reasons.append("ORDER_MUTATION_DETECTED")
    if payload.get("blocked") is True:
        reasons.append("WORKER_BLOCKED")
    if payload.get("error"):
        reasons.append("WORKER_ERROR")
    if payload.get("ok") is not True:
        reasons.append("WORKER_NOT_OK")

    source_age = payload.get("source_age_seconds")
    cache_age = payload.get("instrument_cache_age_seconds")
    if source_age is None:
        reasons.append("SOURCE_FRESHNESS_UNKNOWN")
    elif float(source_age) > MAX_SOURCE_AGE:
        reasons.append("SOURCE_STALE")
    if cache_age is None:
        reasons.append("CACHE_FRESHNESS_UNKNOWN")
    elif float(cache_age) > MAX_CACHE_AGE:
        reasons.append("CACHE_STALE")

    scan = load(SCAN)
    if payload.get("ok") is True and not isinstance(scan, dict):
        reasons.append("SCAN_ARTIFACT_MISSING")
    elif isinstance(scan, dict):
        if scan.get("environment") != "DEMO":
            reasons.append("SCAN_NOT_DEMO")
        if scan.get("orders_submitted") != 0:
            reasons.append("SCAN_ORDER_MUTATION_DETECTED")

    ok = not reasons
    result = {
        "ok": ok,
        "state": "HEALTHY" if ok else "DEGRADED",
        "status_age_seconds": round(status_age, 2),
        "source_age_seconds": source_age,
        "instrument_cache_age_seconds": cache_age,
        "reasons": reasons,
        "run_id": payload.get("run_id"),
        "finished_at": payload.get("finished_at"),
        "evaluated_count": payload.get("evaluated_count"),
        "qualified_count": payload.get("qualified_count"),
        "shortlist_count": payload.get("shortlist_count"),
        "orders_submitted": payload.get("orders_submitted", 0),
        "live_trading_enabled": payload.get("live_trading_enabled"),
    }
    print(json.dumps(result, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

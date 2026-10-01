#!/usr/bin/env python3
"""Daily Trading 212 DEMO instrument-cache refresh. Read-only."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(os.getenv("T212_SCANNER_STATE_DIR", "/var/lib/t212-scanner"))
CACHE = DATA_DIR / "t212_instrument_cache.json"
DIFF = DATA_DIR / "t212_instrument_diff.json"
LOCK = DATA_DIR / "t212_instrument_cache.lock"
STATUS = DATA_DIR / "t212_instrument_cache_status.json"
URL = "https://demo.trading212.com/api/v0/equity/metadata/instruments"

try:
    import fcntl
except ImportError:
    fcntl = None


def atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def diff(previous, current):
    prev = {str(x.get("ticker")): x for x in previous if isinstance(x, dict) and x.get("ticker")}
    cur = {str(x.get("ticker")): x for x in current if isinstance(x, dict) and x.get("ticker")}
    added = [cur[t] for t in sorted(set(cur) - set(prev))]
    removed = [prev[t] for t in sorted(set(prev) - set(cur))]
    tracked = ("name", "shortName", "isin", "currencyCode", "type", "extendedHours", "maxOpenQuantity")
    changed = []
    for ticker in sorted(set(prev) & set(cur)):
        changes = {
            field: {"before": prev[ticker].get(field), "after": cur[ticker].get(field)}
            for field in tracked
            if prev[ticker].get(field) != cur[ticker].get(field)
        }
        if changes:
            changed.append({"ticker": ticker, "changes": changes})
    return {
        "generatedAtEpoch": time.time(),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "baselineWasPresent": bool(previous),
        "addedCount": len(added) if previous else 0,
        "removedCount": len(removed),
        "changedCount": len(changed),
        "added": added if previous else [],
        "removed": removed,
        "changed": changed,
    }


def fingerprint(instruments) -> str:
    canonical = json.dumps(instruments, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def main() -> int:
    started = datetime.now(timezone.utc)
    key = os.getenv("T212_DEMO_API_KEY", "").strip()
    secret = os.getenv("T212_DEMO_API_SECRET", "").strip()
    if not key or not secret:
        atomic(STATUS, {
            "ok": False,
            "environment": "DEMO",
            "started_at": started.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "error_code": "DEMO_CREDENTIALS_UNAVAILABLE",
            "orders_submitted": 0,
        })
        print("ERROR: T212 DEMO credentials unavailable", file=sys.stderr)
        return 2

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with LOCK.open("a+") as lock:
        if fcntl is not None:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        previous_payload = load(CACHE) or {}
        previous = previous_payload.get("instruments", [])

        token = base64.b64encode(f"{key}:{secret}".encode()).decode()
        req = urllib.request.Request(
            URL,
            headers={"Authorization": f"Basic {token}", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                current = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            atomic(STATUS, {
                "ok": False,
                "environment": "DEMO",
                "started_at": started.isoformat(),
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "error_code": "T212_DEMO_METADATA_FETCH_FAILED",
                "error_type": type(exc).__name__,
                "orders_submitted": 0,
            })
            raise

        if not isinstance(current, list) or not current:
            raise RuntimeError("unexpected or empty T212 instrument response")

        fetched_epoch = time.time()
        cache_payload = {
            "provider": "Trading212",
            "environment": "DEMO",
            "source": "equity/metadata/instruments",
            "fetchedAtEpoch": fetched_epoch,
            "fetchedAt": datetime.fromtimestamp(fetched_epoch, timezone.utc).isoformat(),
            "count": len(current),
            "sha256": fingerprint(current),
            "instruments": current,
        }
        atomic(CACHE, cache_payload)
        d = diff(previous, current)
        atomic(DIFF, d)
        status = {
            "ok": True,
            "environment": "DEMO",
            "started_at": started.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "instrument_count": len(current),
            "cache_sha256": cache_payload["sha256"],
            "baseline_was_present": d["baselineWasPresent"],
            "added_count": d["addedCount"],
            "removed_count": d["removedCount"],
            "changed_count": d["changedCount"],
            "orders_submitted": 0,
            "live_trading_enabled": False,
        }
        atomic(STATUS, status)
        print(json.dumps(status, sort_keys=True))
        if fcntl is not None:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

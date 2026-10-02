#!/usr/bin/env python3
"""Produce a fresh, read-only Alpaca market snapshot for deterministic discovery.

This worker has no broker-write path. It runs only inside the same deterministic
Europe/London session boundary as the discovery worker.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from openwebui.tools.scanner_metrics import average_daily_volume_from_bars


STATE = Path(os.getenv("T212_SCANNER_STATE_DIR", "/var/lib/t212-scanner"))
OUTPUT_PATH = Path(os.getenv("T212_MARKET_SNAPSHOT", str(STATE / "market_snapshot.json")))
STATUS_PATH = Path(os.getenv("T212_SNAPSHOT_PRODUCER_STATUS", str(STATE / "snapshot_producer_status.json")))
FEED = os.getenv("T212_MARKET_DATA_FEED", "iex").strip().lower()
QUOTE_MAX_AGE_SECONDS = int(os.getenv("T212_QUOTE_MAX_AGE_SECONDS", "300"))
CANDIDATE_TOP = int(os.getenv("T212_DISCOVERY_CANDIDATE_TOP", "30"))


class SnapshotProductionError(ValueError):
    pass


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    os.chmod(temp, 0o600)
    temp.replace(path)


def _decode(value: Any, label: str) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        raise SnapshotProductionError(f"{label} returned an unexpected response")
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise SnapshotProductionError(f"{label} failed: {value[:240]}") from exc
    if not isinstance(payload, dict):
        raise SnapshotProductionError(f"{label} returned an unexpected JSON shape")
    return payload


def _parse_timestamp(value: Any) -> float | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _latest_observation_epoch(row: dict[str, Any]) -> float | None:
    values = [
        _parse_timestamp(row.get("quoteTimestamp")),
        _parse_timestamp(row.get("tradeTimestamp")),
    ]
    present = [value for value in values if value is not None]
    return max(present) if present else None


def _session_elapsed_fraction(clock: dict[str, Any]) -> float | None:
    if not bool(clock.get("is_open")):
        return None
    now_epoch = _parse_timestamp(clock.get("timestamp"))
    close_epoch = _parse_timestamp(clock.get("next_close"))
    if now_epoch is None or close_epoch is None:
        return None
    regular_session_seconds = 6.5 * 60 * 60
    elapsed = 1.0 - max(0.0, close_epoch - now_epoch) / regular_session_seconds
    return max(0.05, min(elapsed, 1.0))


def _bars_by_symbol(payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    bars = payload.get("bars", payload)
    if not isinstance(bars, dict):
        return {}
    return {
        str(symbol).upper(): rows
        for symbol, rows in bars.items()
        if isinstance(rows, list)
    }


async def produce_snapshot(
    gateway: Any,
    *,
    now_epoch: float | None = None,
    feed: str = FEED,
    max_age_seconds: int = QUOTE_MAX_AGE_SECONDS,
    candidate_top: int = CANDIDATE_TOP,
) -> dict[str, Any]:
    """Build one timestamped broad-discovery snapshot without broker actions."""
    observed_epoch = time.time() if now_epoch is None else float(now_epoch)
    observed_at = datetime.fromtimestamp(observed_epoch, timezone.utc)

    clock = _decode(await gateway.market_clock(), "market clock")
    scan = _decode(
        await gateway.candidate_scan(
            top=max(5, min(int(candidate_top), 30)),
            feed=feed,
        ),
        "candidate scan",
    )
    candidates = scan.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        blockers = [
            str(scan.get("moversError") or ""),
            str(scan.get("mostActiveError") or ""),
            str(scan.get("snapshotError") or ""),
        ]
        detail = "; ".join(item for item in blockers if item)
        raise SnapshotProductionError(
            "candidate scan returned no rows" + (f": {detail}" if detail else "")
        )

    symbols = []
    seen = set()
    for row in candidates:
        symbol = str((row or {}).get("symbol") or "").upper().strip()
        if symbol and symbol not in seen:
            seen.add(symbol)
            symbols.append(symbol)

    bars_start = (observed_at - timedelta(days=40)).isoformat()
    bars_end = observed_at.isoformat()
    bars_payload: dict[str, Any] = {}
    bars_error = None
    try:
        bars_payload = _decode(
            await gateway.bars(
                ",".join(symbols),
                timeframe="1Day",
                start=bars_start,
                end=bars_end,
                limit=10000,
                feed=feed,
            ),
            "daily bars",
        )
    except SnapshotProductionError as exc:
        bars_error = str(exc)

    historical = _bars_by_symbol(bars_payload)
    session_fraction = _session_elapsed_fraction(clock)
    rows = []
    rejected_stale = []

    for raw in candidates:
        if not isinstance(raw, dict):
            continue
        symbol = str(raw.get("symbol") or "").upper().strip()
        if not symbol:
            continue
        observation_epoch = _latest_observation_epoch(raw)
        if observation_epoch is None:
            rejected_stale.append({"symbol": symbol, "reason": "TIMESTAMP_MISSING"})
            continue
        age = max(0.0, observed_epoch - observation_epoch)
        if age > max(1, int(max_age_seconds)):
            rejected_stale.append(
                {
                    "symbol": symbol,
                    "reason": "OBSERVATION_STALE",
                    "observation_age_seconds": round(age, 3),
                }
            )
            continue

        avg20 = average_daily_volume_from_bars(historical.get(symbol, []), 20)
        baseline_source = "completed_20d_bars"
        if avg20 in (None, 0):
            try:
                avg20 = float(raw.get("previousVolume"))
            except (TypeError, ValueError):
                avg20 = None
            baseline_source = (
                "previous_session_fallback" if avg20 not in (None, 0) else "unavailable"
            )

        rows.append(
            {
                **raw,
                "symbol": symbol,
                "avg20_volume": avg20,
                "volume_baseline_source": baseline_source,
                "session_elapsed_fraction": session_fraction,
                "observation_timestamp": datetime.fromtimestamp(
                    observation_epoch, timezone.utc
                ).isoformat(),
                "observation_age_seconds": round(age, 3),
            }
        )

    if not rows:
        raise SnapshotProductionError(
            "all candidate observations were stale or missing timestamps"
        )

    return {
        "source": "alpaca:candidate_scan",
        "source_kind": "live_provider",
        "fixture": False,
        "generated_at": observed_at.isoformat(),
        "freshness_checked_at": observed_at.isoformat(),
        "row_freshness_enforced": True,
        "feed": feed,
        "market_clock": clock,
        "screeners": {
            "movers_error": scan.get("moversError"),
            "most_active_error": scan.get("mostActiveError"),
            "snapshot_error": scan.get("snapshotError"),
        },
        "historical_bars_error": bars_error,
        "input_candidate_count": len(candidates),
        "accepted_row_count": len(rows),
        "stale_rejected_count": len(rejected_stale),
        "stale_rejected": rejected_stale,
        "rows": rows,
        "environment": "DEMO",
        "live_trading_enabled": False,
        "orders_submitted": 0,
    }


async def async_main() -> int:
    # Import here so offline unit tests never require the HTTP client package.
    from openwebui.tools.market_data_gateway import Tools
    from worker.session_gate import evaluate_session

    now = datetime.now(timezone.utc)
    decision = evaluate_session(now)
    if not decision.allowed:
        status = {
            "ok": True,
            "skipped": True,
            "skip_reason": decision.reason,
            "session_gate": decision.to_dict(),
            "environment": "DEMO",
            "live_trading_enabled": False,
            "orders_submitted": 0,
        }
        atomic_json(STATUS_PATH, status)
        print(json.dumps(status, sort_keys=True))
        return 0

    try:
        snapshot = await produce_snapshot(Tools())
        atomic_json(OUTPUT_PATH, snapshot)
        status = {
            "ok": True,
            "skipped": False,
            "generated_at": snapshot["generated_at"],
            "source": snapshot["source"],
            "feed": snapshot["feed"],
            "accepted_row_count": snapshot["accepted_row_count"],
            "stale_rejected_count": snapshot["stale_rejected_count"],
            "environment": "DEMO",
            "live_trading_enabled": False,
            "orders_submitted": 0,
        }
        atomic_json(STATUS_PATH, status)
        print(json.dumps(status, sort_keys=True))
        return 0
    except Exception as exc:
        status = {
            "ok": False,
            "skipped": False,
            "error": f"{type(exc).__name__}: {exc}",
            "environment": "DEMO",
            "live_trading_enabled": False,
            "orders_submitted": 0,
        }
        atomic_json(STATUS_PATH, status)
        print(json.dumps(status, sort_keys=True))
        return 2


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main())


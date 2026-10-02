#!/usr/bin/env python3
"""Fresh market-snapshot adapter for the deterministic T212 DEMO scanner.

This module has no broker-write path. It converts a timestamped market snapshot
plus the Trading212 DEMO instrument cache into scanner-ready rows and fails
closed when either input is stale or unavailable.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openwebui.tools.scanner_metrics import enrich_snapshot


class DiscoveryInputError(ValueError):
    pass


def _parse_timestamp(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str) or not value.strip():
        raise DiscoveryInputError("market snapshot is missing generated_at")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError as exc:
        raise DiscoveryInputError("market snapshot generated_at is invalid") from exc


def load_snapshot(
    path: str | Path,
    *,
    max_age_seconds: int = 300,
    now_epoch: float | None = None,
    allow_fixture: bool = False,
) -> dict[str, Any]:
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise DiscoveryInputError("market snapshot is unavailable") from exc
    except json.JSONDecodeError as exc:
        raise DiscoveryInputError("market snapshot is not valid JSON") from exc

    if isinstance(payload, list):
        raise DiscoveryInputError("market snapshot must include source and generated_at metadata")
    if not isinstance(payload, dict) or not isinstance(payload.get("rows"), list):
        raise DiscoveryInputError("market snapshot must contain a rows array")

    generated = _parse_timestamp(payload.get("generated_at") or payload.get("generatedAt"))
    now = time.time() if now_epoch is None else float(now_epoch)
    age = max(0.0, now - generated)
    if age > max(1, int(max_age_seconds)):
        raise DiscoveryInputError(f"market snapshot is stale ({round(age, 1)}s old)")

    source_name = str(payload.get("source") or "").strip()
    if not source_name:
        raise DiscoveryInputError("market snapshot is missing source")

    source_kind = str(payload.get("source_kind") or "").strip().lower()
    is_fixture = bool(payload.get("fixture")) or source_kind == "closed_market_fixture"
    if is_fixture and not allow_fixture:
        raise DiscoveryInputError("closed-market fixture is not valid live discovery input")
    if not is_fixture and source_kind != "live_provider":
        raise DiscoveryInputError("market snapshot source_kind is not live_provider")
    if payload.get("row_freshness_enforced") is not True:
        raise DiscoveryInputError("market snapshot lacks row-level freshness evidence")

    checked_rows = []
    for row in payload["rows"]:
        if not isinstance(row, dict):
            continue
        try:
            row_age = float(row.get("observation_age_seconds"))
        except (TypeError, ValueError) as exc:
            raise DiscoveryInputError(
                "market snapshot row lacks observation freshness"
            ) from exc
        if row_age < 0 or row_age > max(1, int(max_age_seconds)):
            raise DiscoveryInputError(
                f"market snapshot contains stale observation ({round(row_age, 1)}s old)"
            )
        checked_rows.append(row)

    if not checked_rows:
        raise DiscoveryInputError("market snapshot has no freshness-checked rows")

    return {
        "source": source_name,
        "source_kind": source_kind,
        "fixture": is_fixture,
        "generated_at_epoch": generated,
        "age_seconds": round(age, 3),
        "rows": checked_rows,
    }


def load_instrument_cache(path: str | Path, *, ttl_seconds: int = 86400, now_epoch: float | None = None) -> dict[str, Any]:
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise DiscoveryInputError("T212 DEMO instrument cache is unavailable") from exc
    except json.JSONDecodeError as exc:
        raise DiscoveryInputError("T212 DEMO instrument cache is invalid JSON") from exc

    if payload.get("environment") != "DEMO":
        raise DiscoveryInputError("instrument cache is not DEMO")
    instruments = payload.get("instruments")
    if not isinstance(instruments, list) or not instruments:
        raise DiscoveryInputError("instrument cache has no instruments")
    try:
        fetched = float(payload.get("fetchedAtEpoch", 0))
    except (TypeError, ValueError) as exc:
        raise DiscoveryInputError("instrument cache has invalid freshness metadata") from exc

    now = time.time() if now_epoch is None else float(now_epoch)
    age = max(0.0, now - fetched)
    if age > max(1, int(ttl_seconds)):
        raise DiscoveryInputError(f"instrument cache is stale ({round(age / 3600, 2)}h old)")

    return {
        "age_seconds": round(age, 3),
        "instruments": instruments,
    }


def build_instrument_index(instruments: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for instrument in instruments:
        ticker = str(instrument.get("ticker") or "").upper().strip()
        if not ticker:
            continue
        symbol = str(instrument.get("symbol") or ticker.split("_", 1)[0]).upper().strip()
        if symbol and symbol not in index:
            index[symbol] = instrument
    return index


def _supported_instrument(instrument: dict[str, Any] | None) -> bool:
    if not instrument:
        return False
    instrument_type = str(instrument.get("type") or "").lower()
    if any(token in instrument_type for token in ("warrant", "right", "unit")):
        return False
    status = str(instrument.get("status") or "").lower()
    if status in {"inactive", "delisted", "legacy", "stale"}:
        return False
    return True


def normalize_rows(
    rows: list[dict[str, Any]],
    instruments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    index = build_instrument_index(instruments)
    normalized: list[dict[str, Any]] = []

    for raw in rows:
        if not isinstance(raw, dict):
            continue
        symbol = str(raw.get("symbol") or "").upper().strip()
        if not symbol:
            continue
        instrument = index.get(symbol)
        ticker = str((instrument or {}).get("ticker") or raw.get("t212_ticker") or "").strip() or None
        tradable = _supported_instrument(instrument)

        if all(key in raw for key in ("change_pct", "rel_vol", "dollar_vol")):
            row = dict(raw)
            row["symbol"] = symbol
            row["t212_ticker"] = ticker
            row["tradable"] = bool(tradable and raw.get("tradable", True))
        else:
            row = enrich_snapshot(
                {
                    **raw,
                    "symbol": symbol,
                },
                avg20_volume=raw.get("avg20_volume", raw.get("avg20Volume")),
                t212_ticker=ticker,
                tradable=tradable,
                session_elapsed_fraction=raw.get("session_elapsed_fraction"),
            )

        row["asset_status"] = str(
            raw.get("asset_status")
            or (instrument or {}).get("status")
            or "active"
        ).lower()
        normalized.append(row)

    return normalized

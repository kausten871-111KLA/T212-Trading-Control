"""
title: Trading Brain Research Context (STAGED)
author: OpenAI Engineering
description: Offline evidence-quality, quote economics, bar-feature and history context for the existing Trading Operations model. Accepts structured provider snapshots; does not call APIs or place orders.
version: 0.1.0
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel
from research_context import compile_context
from market_gateway_normalizer import normalise_snapshot, normalise_bars

MAX_SNAPSHOT_CHARS = 60_000
MAX_DECISION_CHARS = 12_000
MAX_BARS_CHARS = 100_000
MEMORY_DB = Path("/app/backend/data/trading_brain_research/finmem.sqlite3")


class Tools:
    """Research-only augmentation. No broker, subprocess or network access."""

    def __init__(self):
        self.valves = self.Valves()

    class Valves(BaseModel):
        pass

    async def trading_brain_research(
        self,
        ticker: str,
        snapshot_json: str,
        as_of_utc: str,
        decision_json: str = "{}",
        bars_json: str = "[]",
        average_daily_volume: Optional[float] = None,
        scenario_quantity: int = 100,
    ) -> str:
        """Combine actual supplied market evidence into a structured research-context packet.

        :param ticker: Exact ticker from the supplied market snapshot (e.g. MYGN).
        :param snapshot_json: JSON from the existing market-data tool, including observation_timestamp_utc and candidates or observation. NOT a news claim.
        :param as_of_utc: ISO-8601 time with timezone, used for point-in-time analysis.
        :param decision_json: Optional previous analyst decision object for advisory comparison; never changes its action.
        :param bars_json: Optional timestamped OHLCV list. No bars means null momentum values, not invented data.
        :param average_daily_volume: Optional independently supplied comparable-volume baseline. Null means unknown RVOL.
        :param scenario_quantity: Hypothetical share quantity for spread-cost maths, not an order size or cap.
        """
        try:
            if not isinstance(snapshot_json, str) or len(snapshot_json) > MAX_SNAPSHOT_CHARS:
                raise ValueError("snapshot_json exceeds research size limit")
            if not isinstance(decision_json, str) or len(decision_json) > MAX_DECISION_CHARS:
                raise ValueError("decision_json exceeds research size limit")
            if not isinstance(bars_json, str) or len(bars_json) > MAX_BARS_CHARS:
                raise ValueError("bars_json exceeds research size limit")
            raw = json.loads(snapshot_json)
            decision = json.loads(decision_json)
            bars = json.loads(bars_json)
            if not isinstance(raw, dict):
                raise ValueError("snapshot must be a JSON object")
            if not isinstance(decision, dict):
                raise ValueError("decision must be a JSON object")
            # Retain exact quote/trade timestamps and source provenance.
            # Never manufacture RVOL, VWAP, exchange or a news catalyst.
            raw = normalise_snapshot(raw, ticker=ticker, as_of_utc=as_of_utc)
            bars = normalise_bars(bars, ticker=ticker)
            if not 1 <= scenario_quantity <= 100_000:
                raise ValueError("scenario_quantity must be 1..100000")
            if average_daily_volume is not None and average_daily_volume <= 0:
                raise ValueError("comparative volume must be positive")
            if not decision:
                decision = None
            # Separately approved research-only DB may be mounted in a future
            # release. Missing DB yields zero history, never creates a new file.
            db = None
            if MEMORY_DB.is_file():
                import sqlite3
                db = sqlite3.connect(
                    "file:" + str(MEMORY_DB) + "?mode=ro", uri=True, timeout=4
                )
                db.row_factory = sqlite3.Row
            try:
                result = compile_context(
                    raw, ticker=ticker, as_of_utc=as_of_utc,
                    decision=decision, bars=bars,
                    average_daily_volume=average_daily_volume,
                    quantity=scenario_quantity, memory_db=db,
                )
            finally:
                if db is not None:
                    db.close()
            # Output length is bounded, so one snapshot cannot overwhelm the model.
            serialized = json.dumps(result, ensure_ascii=False, separators=(",",":"))
            if len(serialized) > 35_000:
                raise ValueError("research result too large")
            return serialized
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            return json.dumps({
                "ok": False,
                "error": "invalid_research_input",
                "error_type": type(exc).__name__,
                "research_only": True,
                "broker_orders": 0,
            })

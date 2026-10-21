"""Trading Brain research context: a single, broker-neutral evidence envelope.

Consumes external observations supplied by an existing market-data tool;
never downloads data, calls a model, places an order, or changes decisions.
Memory is point-in-time and may only contain previously observed decisions.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import re
from typing import Any

from evidence_review import assess_decision
from finmem_research import retrieve
from momentum_features import analyse_bars
from quote_economics import quote_economics

SYMBOL = re.compile(r"[A-Z0-9][A-Z0-9._^-]{0,20}\Z")
ALLOWED_FIELDS = (
    "ticker", "price", "change_pct", "day_volume", "bid", "ask",
    "spread_pct", "exchange", "vwap", "rvol", "catalyst", "stale",
    "quote_time_utc", "trade_time_utc", "source", "source_tier",
)
MAX_BARS = 800
MAX_MEMORIES = 20


def _iso_utc(value: str) -> str:
    if not isinstance(value, str) or len(value) > 50:
        raise ValueError("Explicit bounded timestamp required")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Invalid timestamp") from exc
    if result.tzinfo is None:
        raise ValueError("Timezone required")
    return result.astimezone(timezone.utc).isoformat()


def _finite(value: Any, *, allow_none=True):
    if value is None and allow_none:
        return None
    if isinstance(value, bool):
        raise ValueError("Boolean is not a price or quantity")
    try:
        v = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError("Invalid numeric market field") from exc
    if not math.isfinite(v):
        raise ValueError("Non-finite market data")
    return v


def _lookup(data: dict, ticker: str) -> dict:
    if "candidates" in data:
        entries = data["candidates"]
        if not isinstance(entries, list) or not 0 < len(entries) <= 100:
            raise ValueError("Invalid candidate list size")
        matches = [x for x in entries if isinstance(x, dict)
                   and x.get("ticker") == ticker]
        if len(matches) != 1:
            raise ValueError("Ticker must occur exactly once in supplied dataset")
        return matches[0]
    row = data.get("observation")
    if not isinstance(row, dict) or row.get("ticker") != ticker:
        raise ValueError("Ticker mismatch")
    return row


def compile_context(
    data: dict, *,
    ticker: str,
    as_of_utc: str,
    decision: dict | None = None,
    bars: list[dict] | None = None,
    average_daily_volume: float | None = None,
    memory_db=None,
    quantity: int = 100,
) -> dict:
    """Create a deterministic, evidence-first research context packet.

    The input snapshot's capture time, not its content labels, establishes
    the earliest credible availability. A subsequent live quote must carry
    its own timestamp before its freshness can be verified.
    """
    if not isinstance(data, dict):
        raise ValueError("A structured snapshot is required")
    sym = ticker.strip().upper() if isinstance(ticker, str) else ""
    if not SYMBOL.fullmatch(sym):
        raise ValueError("Invalid ticker")
    now = _iso_utc(as_of_utc)
    observed = _iso_utc(data.get("observation_timestamp_utc"))
    if observed > now:
        raise ValueError("Future snapshot cannot be used")
    row = _lookup(data, sym)

    # Reject malformed provider numbers rather than silently treating them as a signal.
    for name in ("price", "change_pct", "day_volume", "bid", "ask", "spread_pct", "vwap", "rvol"):
        _finite(row.get(name))
    if row.get("day_volume") is not None and _finite(row["day_volume"]) < 0:
        raise ValueError("Negative day volume")

    quote_ts = row.get("quote_time_utc")
    if quote_ts is not None:
        quote_ts = _iso_utc(quote_ts)
        if quote_ts > now:
            raise ValueError("Future quote timestamp")
    trade_ts = row.get("trade_time_utc")
    if trade_ts is not None:
        trade_ts = _iso_utc(trade_ts)
        if trade_ts > now:
            raise ValueError("Future trade timestamp")

    # This envelope does not assume data is exchange-specific, time-synchronised
    # or executable. Data provenance is declared by source, not independently proven.
    factual = {key:row.get(key) for key in ALLOWED_FIELDS}
    factual["ticker"] = sym
    factual["quote_time_utc"] = quote_ts
    factual["trade_time_utc"] = trade_ts
    factual["catalyst"] = None  # Separate unverified natural-language hypothesis below.
    source = str(data.get("data_source") or "UNSPECIFIED")[:300]
    observed_hypothesis = row.get("catalyst")
    if not isinstance(observed_hypothesis, str):
        observed_hypothesis = None
    if observed_hypothesis:
        observed_hypothesis = observed_hypothesis[:450]

    evidence = {
        "dataset_id": str(data.get("dataset_id") or "unspecified")[:150],
        "ticker": sym,
        "market_observation_time_utc": observed,
        "as_of_utc": now,
        "data_source_claim": source,
        "observation_time_is_caller_supplied": bool(
            data.get("source_capture_time_supplied_by_caller")),
        "source_raw_receipt_independently_verified": False,
        "observation": factual,
    }
    digest = hashlib.sha256(
        json.dumps(evidence, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        .encode("utf-8")
    ).hexdigest()

    quote = quote_economics({
        "ticker":sym, "bid":row.get("bid"),"ask":row.get("ask"),
        "quote_time_utc":quote_ts,
    }, quantity=quantity)

    bars = [] if bars is None else bars
    if not isinstance(bars, list) or len(bars) > MAX_BARS:
        raise ValueError("Invalid bar count")
    bar_analysis = analyse_bars(
        bars, as_of_utc=now, average_daily_volume=average_daily_volume
    )
    memory = retrieve(memory_db, as_of_utc=now, ticker=sym, limit=MAX_MEMORIES) if memory_db is not None else []
    audit = assess_decision(decision, row) if decision is not None else None

    source_missing = [
        key for key in ("exchange", "price", "bid", "ask", "rvol", "vwap")
        if row.get(key) is None
    ]
    if data.get("source_capture_time_supplied_by_caller"):
        source_missing.append("provider_attested_snapshot_capture_time")
    if not quote_ts:
        source_missing.append("timestamped_bid_ask_quote")
    if not trade_ts:
        source_missing.append("timestamped_last_trade")
    if observed_hypothesis and observed_hypothesis.lower() not in ("unknown", "none"):
        source_missing.append("independent_primary_catalyst_source")
    output = {
        "schema_version": 1,
        "research_only": True,
        "broker_order_instructions": False,
        "decision_action_changed": False,
        "ticker": sym,
        "as_of_utc": now,
        "evidence_sha256": digest,
        "source_evidence": evidence,
        "catalyst_hypothesis_unverified": observed_hypothesis,
        "quote_economics_hypothetical": quote,
        "bar_features": bar_analysis,
        "history_as_of": memory,
        "decision_quality_advisory": audit,
        "missing_evidence": sorted(set(source_missing)),
        "limitations": [
            "This envelope does not establish current market tradability",
            "Snapshot and catalyst descriptions are source claims, not primary evidence",
            "Quoted bid/ask is historical and not a broker execution or fill",
            "Momentum requires timestamped bars; RVOL needs a comparable volume baseline",
            "No trade caps, thresholds or hard-coded stock exclusions are imposed",
        ],
    }
    return output

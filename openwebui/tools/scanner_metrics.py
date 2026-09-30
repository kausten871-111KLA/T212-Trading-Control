"""
title: Scanner Metrics Core
author: Katie / OpenAI
description: Deterministic calculations for relative volume, dollar volume, spread and price-move metrics. No broker writes and no LLM calls.
version: 0.1.0
"""

from typing import Any, Dict, Iterable, List, Optional


def _f(value, default=None):
    try:
        return float(value)
    except Exception:
        return default


def average_daily_volume_from_bars(
    bars: Iterable[Dict[str, Any]],
    lookback_days: int = 20,
) -> Optional[float]:
    """
    Compute mean daily volume from the most recent completed daily bars.
    Expects Alpaca-style bars with volume in 'v'.
    """
    rows: List[float] = []
    for bar in bars:
        volume = _f((bar or {}).get("v"))
        if volume is not None and volume >= 0:
            rows.append(volume)

    if not rows:
        return None

    rows = rows[-max(1, int(lookback_days)):]
    return sum(rows) / len(rows)


def enrich_snapshot(
    snapshot: Dict[str, Any],
    avg20_volume: Optional[float],
    t212_ticker: Optional[str] = None,
    tradable: bool = False,
    session_elapsed_fraction: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Convert one market snapshot + historical-volume baseline into scanner-ready metrics.
    """
    price = _f(snapshot.get("price"))
    day_volume = _f(snapshot.get("dayVolume"))
    previous_close = _f(snapshot.get("previousClose"))
    bid = _f(snapshot.get("bid"))
    ask = _f(snapshot.get("ask"))

    change_pct = None
    if price is not None and previous_close not in (None, 0):
        change_pct = (price / previous_close - 1.0) * 100.0

    rel_vol = None
    rel_vol_method = None
    if day_volume is not None and avg20_volume not in (None, 0):
        if session_elapsed_fraction is not None:
            elapsed = max(0.05, min(float(session_elapsed_fraction), 1.0))
            expected_volume_to_now = avg20_volume * elapsed
            rel_vol = day_volume / expected_volume_to_now if expected_volume_to_now else None
            rel_vol_method = "elapsed_session_pace"
        else:
            rel_vol = day_volume / avg20_volume
            rel_vol_method = "full_day_baseline_crude"

    spread_pct = None
    if bid not in (None, 0) and ask not in (None, 0) and ask >= bid:
        mid = (bid + ask) / 2.0
        if mid:
            spread_pct = (ask - bid) / mid * 100.0

    dollar_vol = None
    if price is not None and day_volume is not None:
        dollar_vol = price * day_volume

    return {
        "symbol": snapshot.get("symbol"),
        "t212_ticker": t212_ticker,
        "price": price,
        "previous_close": previous_close,
        "change_pct": change_pct,
        "day_volume": day_volume,
        "avg20_volume": avg20_volume,
        "rel_vol": rel_vol,
        "rel_vol_method": rel_vol_method,
        "bid": bid,
        "ask": ask,
        "spread_pct": spread_pct,
        "dollar_vol": dollar_vol,
        "tradable": bool(tradable),
        "quote_ts": snapshot.get("quoteTimestamp"),
        "trade_ts": snapshot.get("tradeTimestamp"),
    }

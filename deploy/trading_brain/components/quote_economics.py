"""Research-only quote/spread economics from frozen observations.

Never treats a quote as executable and never prescribes a trade cutoff.
No Trading 212 credentials or order API.
"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

def _positive_number(value, name):
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(name + " must be numeric")
    try:
        number = Decimal(str(value))
    except (ValueError, InvalidOperation) as exc:
        raise ValueError(name + " not numeric") from exc
    if not number.is_finite() or number <= 0:
        raise ValueError(name + " must be positive and finite")
    return number

def quote_economics(row, *, quantity=1, fee_per_side=0, slippage_each_side=0):
    """Worst-case immediate buy at ask, sell at bid, optional costs.

    Numbers in quote currency. Slippage is a scenario input, not verified data.
    Returns null costs where no complete valid bid/ask pair exists.
    """
    ticker = str(row.get("ticker") or "").strip()
    if not ticker:
        raise ValueError("ticker required")
    qty = _positive_number(quantity, "quantity")
    fee = Decimal(str(fee_per_side))
    slippage = Decimal(str(slippage_each_side))
    if any(not x.is_finite() or x < 0 for x in (fee,slippage)):
        raise ValueError("Fees and slippage must be non-negative finite")
    bid = _positive_number(row.get("bid"), "bid")
    ask = _positive_number(row.get("ask"), "ask")
    if (bid is None) != (ask is None):
        raise ValueError("incomplete bid/ask pair")
    base = {
        "ticker": ticker,
        "observation_only": True,
        "quote_time_utc": row.get("quote_time_utc"),
        "freshness_verified": False,
        "scenario_quantity": str(qty),
        "bid": str(bid) if bid is not None else None,
        "ask": str(ask) if ask is not None else None,
        "roundtrip_spread_cost": None,
        "roundtrip_total_cost": None,
        "spread_pct_mid": None,
        "quote_status": "MISSING_QUOTE" if bid is None else "OBSERVED_NOT_EXECUTABLE",
    }
    if bid is None:
        return base
    if bid > ask:
        raise ValueError("crossed bid/ask")
    mid = (bid + ask) / 2
    spread_cost = (ask - bid) * qty
    scenario = spread_cost + (fee + slippage) * 2
    base.update({
        "spread_pct_mid": float((ask-bid)/mid*100),
        "roundtrip_spread_cost": str(spread_cost),
        "roundtrip_total_cost": str(scenario),
        "quote_status": "OBSERVED_NOT_EXECUTABLE",
    })
    return base

def quote_audit(rows, **scenario):
    return [quote_economics(row, **scenario) for row in rows]

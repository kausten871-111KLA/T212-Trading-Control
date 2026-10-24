"""Timestamped research-only bar calculations (not broker execution signals)."""
from __future__ import annotations
from datetime import datetime, timezone
import math

def _timestamp(value):
    if not isinstance(value,str):
        raise ValueError("UTC timestamp required")
    t=datetime.fromisoformat(value.replace("Z","+00:00"))
    if t.tzinfo is None:
        raise ValueError("naive timestamp")
    return t.astimezone(timezone.utc)

def _float(v, name):
    if isinstance(v,bool) or v is None:
        raise ValueError(name+" numeric required")
    try:
        n=float(v)
    except (TypeError, ValueError) as e:
        raise ValueError(name+" invalid") from e
    if not math.isfinite(n):
        raise ValueError(name+" invalid")
    return n

def analyse_bars(bars, *, as_of_utc, average_daily_volume=None):
    """Compute price return, available period VWAP and conditional RVOL.

    Bar timestamps must be distinct, sorted and no later than the cutoff.
    RVOL needs a supplied historical comparable-volume baseline. Never
    substitutes absolute volume or an arbitrary reference for RVOL.
    """
    cutoff=_timestamp(as_of_utc)
    prev=None
    seen=[]
    for r in bars:
        t=_timestamp(r["timestamp_utc"])
        if t > cutoff:
            raise ValueError("future bar violates point-in-time boundary")
        if prev is not None and t <= prev:
            raise ValueError("bars must be strictly ascending")
        prev=t
        close=_float(r["close"],"close")
        volume=_float(r["volume"],"volume")
        if close <= 0 or volume < 0:
            raise ValueError("invalid close or volume")
        high=_float(r.get("high",close),"high")
        low=_float(r.get("low",close),"low")
        if low <= 0 or low > close or close > high:
            raise ValueError("invalid high/low/close")
        seen.append((t,close,volume,high,low))
    out={
        "as_of_utc":cutoff.isoformat(),
        "bars":len(seen),
        "first_bar_utc":seen[0][0].isoformat() if seen else None,
        "last_bar_utc":seen[-1][0].isoformat() if seen else None,
        "momentum_return_pct":None,
        "volume_weighted_price":None,
        "relative_volume":None,
        "missing_inputs":[],
        "not_an_executable_quote":True,
    }
    if len(seen)>=2:
        out["momentum_return_pct"]=(seen[-1][1]/seen[0][1]-1)*100
    else:
        out["missing_inputs"].append("At least two timestamped bars")
    total=sum(x[2] for x in seen)
    if total>0:
        out["volume_weighted_price"]=sum(((x[3]+x[4]+x[1])/3)*x[2] for x in seen)/total
    else:
        out["missing_inputs"].append("Non-zero volume for VWAP proxy")
    if average_daily_volume is None:
        out["missing_inputs"].append("Historical comparable-volume baseline for RVOL")
    else:
        av=_float(average_daily_volume,"average_daily_volume")
        if av<=0:raise ValueError("baseline volume must be positive")
        if seen:out["relative_volume"]=total/av
        else:out["missing_inputs"].append("Observed volume for RVOL")
    return out

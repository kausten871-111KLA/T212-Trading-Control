"""Adapt actual market_data_gateway snapshots/bars without invented fields.

The existing Open WebUI Alpaca gateway returns:
  snapshots: {"provider":"Alpaca","feed":"iex","readOnly":true,
              "symbols":[{"symbol":"MYGN","price":..,"bid":..,...}]}
  bars: {"bars":{"MYGN":[{"t":ISO8601,"o":..,"h":..,"l":..,"c":..,"v":..}]}}

Capturing time is user-provided, not a provider-signed timestamp. The output
marks this explicitly and carries original vendor quote/trade timestamps.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _normal_time(value: str) -> str:
    if not isinstance(value, str) or len(value) > 50:
        raise ValueError("Timezone-aware observation time required")
    try:
        result = datetime.fromisoformat(value.replace("Z","+00:00"))
    except ValueError as exc:
        raise ValueError("Invalid observation time") from exc
    if result.tzinfo is None:
        raise ValueError("Timezone required")
    return result.astimezone(timezone.utc).isoformat()


def _symbol(value: str):
    if not isinstance(value,str) or not value.strip():
        raise ValueError("Ticker required")
    return value.strip().upper()


def normalise_snapshot(data: dict, *, ticker: str, as_of_utc: str) -> dict:
    """Accept either the research fixture format or *actual* Alpaca gateway JSON."""
    if not isinstance(data, dict):
        raise ValueError("Market snapshot must be JSON object")
    if "candidates" in data or "observation" in data:
        return data
    if data.get("provider") != "Alpaca" or data.get("readOnly") is not True:
        raise ValueError("Unsupported market data source")
    if data.get("feed") not in ("iex","sip","delayed_sip","boats","overnight","otc"):
        raise ValueError("Missing recognised feed")
    symbols = data.get("symbols")
    if not isinstance(symbols,list) or len(symbols)>30:
        raise ValueError("Malformed market-data gateway symbols")
    symbol = _symbol(ticker)
    hits=[row for row in symbols if isinstance(row,dict)
          and str(row.get("symbol") or "").upper()==symbol]
    if len(hits)!=1:
        raise ValueError("Requested ticker not unique in snapshot")
    r=hits[0]
    observed = _normal_time(as_of_utc)
    return {
        "dataset_id":"alpaca-gateway-"+data["feed"]+"-"+symbol+"-"+observed,
        "observation_timestamp_utc":observed,
        "market_state":"not independently verified",
        "data_source":"Alpaca " + data["feed"] + " through existing WebUI gateway; research input",
        "source_capture_time_supplied_by_caller":True,
        "source_raw_receipt_independently_verified":False,
        "observation":{
            "ticker":symbol,
            "price":r.get("price"),
            "change_pct":r.get("changePctVsPrevClose"),
            "day_volume":r.get("dayVolume"),
            "bid":r.get("bid"),
            "ask":r.get("ask"),
            "spread_pct":r.get("spreadPct"),
            "exchange":None,
            "vwap":None,
            "rvol":None,
            "catalyst":None,
            "stale":None,
            "quote_time_utc":r.get("quoteTimestamp"),
            "trade_time_utc":r.get("tradeTimestamp"),
            "source":"Alpaca " + data["feed"] + " gateway output",
            "source_tier":"gateway_result_not_independently_attested",
        },
    }


def normalise_bars(data: Any, *, ticker: str) -> list[dict]:
    """Accept an already-normalised list or the Alpaca /v2/stocks/bars payload."""
    if isinstance(data,list):
        return data
    if not isinstance(data,dict) or not isinstance(data.get("bars"),dict):
        raise ValueError("Bars must be a list or Alpaca bar response")
    symbol=_symbol(ticker)
    bar_rows=data["bars"].get(symbol)
    if not isinstance(bar_rows,list):
        raise ValueError("Bars response missing requested symbol")
    if len(bar_rows)>800:
        raise ValueError("Bar list exceeds research bound")
    out=[]
    for bar in bar_rows:
        if not isinstance(bar,dict):
            raise ValueError("Invalid bar record")
        out.append({
            "timestamp_utc":bar.get("t"),
            "close":bar.get("c"),
            "volume":bar.get("v"),
            "high":bar.get("h"),
            "low":bar.get("l"),
        })
    return out

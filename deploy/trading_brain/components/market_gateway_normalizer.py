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
    if data.get("provider") == "Twelve Data" and data.get("endpoint") == "quote":
        if data.get("ok") is not True:
            raise ValueError("Unsuccessful Twelve Data quote")
        sym = _symbol(ticker)
        actual = _symbol(data.get("symbol") or data.get("requested_symbol"))
        if actual != sym:
            raise ValueError("Twelve Data returned a different ticker")
        observed = _normal_time(as_of_utc)
        return {
            "dataset_id": "twelve-data-quote-"+sym+"-"+observed,
            "observation_timestamp_utc": observed,
            "data_source": "Twelve Data quote via existing Contabo authenticated bridge",
            "source_capture_time_supplied_by_caller": True,
            "source_raw_receipt_independently_verified": False,
            "observation": {
                "ticker":sym,
                "price":data.get("close"),
                "change_pct":data.get("change_percent"),
                "day_volume":data.get("volume"),
                "bid":data.get("bid"),
                "ask":data.get("ask"),
                "spread_pct":None,
                "exchange":data.get("exchange"),
                "mic_code":data.get("mic_code"),
                "currency":data.get("currency"),
                "exchange_timezone":data.get("exchange_timezone"),
                "vwap":None,"rvol":None,"catalyst":None,"stale":None,
                # Provider's date-only quote datetime is NOT a UTC trade time.
                "provider_market_datetime":data.get("datetime"),
                "quote_time_utc":None,
                "trade_time_utc":None,
                "source":"Twelve Data "+str(data.get("endpoint")),
                "source_tier":"provider_result_not_exchange_verified",
            },
        }
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
    if isinstance(data,dict) and data.get("provider") == "Twelve Data" and data.get("endpoint") == "time_series":
        if data.get("ok") is not True:
            raise ValueError("Unsuccessful Twelve Data time series")
        if data.get("requested_symbol") != _symbol(ticker):
            raise ValueError("Twelve Data bars do not match ticker")
        if data.get("bar_time_basis") != "UTC_requested_provider_series":
            # Daily bars use exchange-local DATE with no UTC instant; never
            # invent a timestamp for intraday momentum calculations.
            raise ValueError("Exchange-local daily bars need separate daily analysis")
        entries=data.get("values")
        if not isinstance(entries,list) or len(entries)>800:
            raise ValueError("Invalid Twelve Data bar list")
        converted=[]
        for entry in entries:
            if not isinstance(entry,dict):
                raise ValueError("Invalid Twelve Data bar")
            stamp=entry.get("datetime")
            if not isinstance(stamp,str):
                raise ValueError("Missing Twelve Data bar time")
            point=datetime.fromisoformat(stamp.replace(" ","T"))
            if point.tzinfo is not None:
                point=point.astimezone(timezone.utc)
            else:
                point=point.replace(tzinfo=timezone.utc)  # UTC explicitly requested
            converted.append({
                "timestamp_utc":point.isoformat(),
                "close":entry.get("close"),"volume":entry.get("volume"),
                "high":entry.get("high"),"low":entry.get("low"),
            })
        return sorted(converted,key=lambda x:x["timestamp_utc"])
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

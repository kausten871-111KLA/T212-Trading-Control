"""Read-only normalizer for the actual Trading 212 DEMO recent_order_history shape.

Saved Open WebUI tool responses are not fresh broker verification. This module
does not execute trades, write FinMem, calculate P&L or authenticate orders.
"""
from __future__ import annotations
from collections import Counter,defaultdict
from datetime import datetime,timezone
from decimal import Decimal,InvalidOperation
import hashlib,json,re

_TICKER=re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,28}\Z")
_CURRENCY=re.compile(r"[A-Z]{3}\Z")

def decode_saved_response(output):
    """Unwrap WebUI v0.12.3 function_call_output.output text envelopes."""
    if isinstance(output,list) and len(output)==1 and isinstance(output[0],dict) and output[0].get("type")=="text":
        output=output[0].get("text")
    if isinstance(output,str):
        if len(output.encode())>250000:raise ValueError("oversized history output")
        try:output=json.loads(output)
        except (ValueError,UnicodeError):raise ValueError("invalid history JSON") from None
    if not isinstance(output,dict) or not isinstance(output.get("items"),list):
        raise ValueError("history page items required")
    if len(output["items"])>500:raise ValueError("oversized history page")
    return output

def _id(value):
    if isinstance(value,bool) or not isinstance(value,(str,int)) or not str(value).isascii() or not str(value).isdecimal() or int(value)<1:
        raise ValueError("invalid broker identifier")
    return str(value)

def _num(value):
    if isinstance(value,bool) or not isinstance(value,(int,float,str)):
        raise ValueError("invalid number")
    try:d=Decimal(str(value))
    except InvalidOperation:raise ValueError("invalid number") from None
    if not d.is_finite() or d<=0:raise ValueError("invalid number")
    return format(d.normalize(),"f")

def _time(value):
    if not isinstance(value,str):raise ValueError("missing filledAt")
    try:ts=datetime.fromisoformat(value.replace("Z","+00:00"))
    except ValueError:raise ValueError("invalid filledAt") from None
    if ts.tzinfo is None:raise ValueError("timezone missing")
    return ts.astimezone(timezone.utc).isoformat()

def normalise_saved_history(output):
    """Conservative per-page candidates; never ready for direct broker import.

    No partial-fill aggregation. Duplicates with differing payloads, multiple
    fill IDs for one order, or inconsistent quantities are quarantined.
    """
    page=decode_saved_response(output)
    counts=Counter()
    candidates=[]
    quarantined=0
    for entry in page["items"]:
        if not isinstance(entry,dict) or not isinstance(entry.get("order"),dict):
            quarantined+=1;continue
        order=entry["order"]
        status=order.get("status")
        if isinstance(status,str):counts[status]+=1
        if status!="FILLED":continue
        try:
            fill=entry.get("fill")
            if not isinstance(fill,dict):raise ValueError("missing fill")
            oid=_id(order.get("id"));fid=_id(fill.get("id"))
            ticker=order.get("ticker");side=order.get("side");currency=order.get("currency")
            if not isinstance(ticker,str) or not _TICKER.fullmatch(ticker):raise ValueError("invalid ticker")
            if side not in ("BUY","SELL"):raise ValueError("invalid side")
            if not isinstance(currency,str) or not _CURRENCY.fullmatch(currency):raise ValueError("invalid currency")
            instrument=order.get("instrument")
            if isinstance(instrument,dict):
                if instrument.get("ticker") not in (None,ticker) or instrument.get("currency") not in (None,currency):
                    raise ValueError("inconsistent instrument")
            core={"brokerOrderId":oid,"brokerFillId":fid,"ticker":ticker.upper(),"side":side,
                  "filledQuantity":_num(fill.get("quantity")),
                  "orderFilledQuantity":_num(order.get("filledQuantity")),
                  "averagePrice":_num(fill.get("price")),"currency":currency,
                  "filledAt":_time(fill.get("filledAt"))}
            digest=hashlib.sha256(json.dumps(core,sort_keys=True,separators=(",",":")).encode()).hexdigest()
            candidates.append({**core,"saved_record_sha256":digest,"status":"FILLED",
                   "environment":"DEMO","source":"SAVED_WEBUI_T212_HISTORY_UNCONFIRMED",
                   "broker_verified":False,"realisedPnL":None})
        except (ValueError,TypeError,OverflowError):
            quarantined+=1
    grouped=defaultdict(list)
    for row in candidates:grouped[row["brokerOrderId"]].append(row)
    safe=[]
    for rows in grouped.values():
        if (len({(r["brokerFillId"],r["saved_record_sha256"]) for r in rows})!=1
            or any(Decimal(r["filledQuantity"])!=Decimal(r["orderFilledQuantity"]) for r in rows)):
            quarantined+=len(rows)
        else:safe.append(rows[0])
    return {"candidates":safe,"status_counts":dict(counts),"quarantined_items":quarantined,
            "page_has_next":bool(page.get("nextPagePath")),
            "broker_verified":False,"finmem_outcomes_written":0,"orders_placed":0}

def safe_summary(result):
    """No IDs, symbols, prices or broker credentials in operational logs."""
    return {"candidate_count":len(result["candidates"]),"status_counts":result["status_counts"],
            "quarantined_items":result["quarantined_items"],"page_has_next":result["page_has_next"],
            "broker_verified":False,"finmem_outcomes_written":0,"orders_placed":0}

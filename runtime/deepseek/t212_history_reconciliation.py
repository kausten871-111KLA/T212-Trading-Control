"""Verify correspondence of saved T212 history and a new authorised DEMO read.

Trust boundary: caller MUST make an independently authenticated, fresh T212
DEMO recent_order_history call. A boolean acknowledgement is not cryptographic
proof; never accept model prose or the saved WebUI DB as the fresh source.

This code does not call the broker, trade, write to FinMem, or calculate P&L.
"""
from __future__ import annotations
from datetime import datetime,timezone
import hashlib,json,re
from runtime.deepseek.t212_history_page_normalizer import normalise_saved_history

_COMPARE=("brokerOrderId","brokerFillId","ticker","side","filledQuantity",
          "orderFilledQuantity","averagePrice","currency","filledAt","saved_record_sha256")

def _utc(t):
    if not isinstance(t,str):raise ValueError("attested UTC timestamp required")
    try:dt=datetime.fromisoformat(t.replace("Z","+00:00"))
    except ValueError:raise ValueError("invalid timestamp") from None
    if dt.tzinfo is None:raise ValueError("timestamp timezone required")
    return dt.astimezone(timezone.utc)

def reconcile_saved_against_fresh(saved_candidate, fresh_history_page, *,
                                  fresh_authenticated_demo_call:bool,
                                  attested_at_utc:str):
    """Return a canonical fill *candidate* after explicit independently fresh call.

    Returns no P&L and no research-decision attribution. Caller must retain the
    genuine broker response and independently validate the authenticated scope.
    This does not certify an account or authenticate requests by itself.
    """
    if fresh_authenticated_demo_call is not True:
        raise ValueError("fresh authenticated DEMO call not attested")
    checked=_utc(attested_at_utc)
    if not isinstance(saved_candidate,dict) or saved_candidate.get("source")!="SAVED_WEBUI_T212_HISTORY_UNCONFIRMED" or saved_candidate.get("broker_verified") is not False:
        raise ValueError("unverified WebUI history candidate required")
    latest=normalise_saved_history(fresh_history_page)
    matching=[x for x in latest["candidates"] if x["brokerOrderId"]==saved_candidate.get("brokerOrderId")]
    if len(matching)!=1:raise ValueError("broker order absent, partial or ambiguous in fresh history")
    fresh=matching[0]
    if any(fresh.get(k)!=saved_candidate.get(k) for k in _COMPARE):
        raise ValueError("fresh broker history differs from saved evidence")
    if _utc(fresh["filledAt"])>checked:
        raise ValueError("future fill compared to fresh attestation")
    core={k:fresh[k] for k in ("brokerOrderId","brokerFillId","ticker","side",
        "filledQuantity","averagePrice","currency","filledAt")}
    core.update({"status":"FILLED","source":"T212_DEMO_RECENT_ORDER_HISTORY",
                 "environment":"DEMO","fresh_broker_read_attested_at_utc":checked.isoformat(),
                 "research_decision_linked":False,"realisedPnL":None,
                 "independent_fresh_call_required":True})
    body=json.dumps(core,sort_keys=True,separators=(",",":"))
    core["reconciliation_sha256"]=hashlib.sha256(body.encode()).hexdigest()
    return core

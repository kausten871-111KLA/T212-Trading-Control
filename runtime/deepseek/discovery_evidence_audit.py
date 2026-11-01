"""Pure read-only evidence audit; no web calls, inference or broker writes."""
from datetime import datetime, timezone

VALID_KINDS = frozenset(("source_row", "candidate", "decision", "trade"))

def _instant(value):
    if not isinstance(value, str):
        raise ValueError("UTC-offset timestamp required")
    t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if t.tzinfo is None or t.utcoffset() is None:
        raise ValueError("Naive timestamp is not evidence")
    return t.astimezone(timezone.utc)

def audit_discovery(symbol, *, events, major_move_at=None, identity_verified=False,
                    instrument_type=None):
    """Evidence states are not predictive returns or proof of missed trades.

    Event: {symbol, kind, at, source}. A source_row requires a saved runner
    ingestion log, not a retrospectively viewed winners web page.
    """
    if not isinstance(symbol, str) or not symbol.strip():
        raise ValueError("Symbol required")
    if not isinstance(events, list):
        raise ValueError("Events list required")
    symbol = symbol.upper().strip()
    timeline = []
    for e in events:
        if not isinstance(e, dict) or e.get("kind") not in VALID_KINDS:
            raise ValueError("Invalid event kind")
        if not isinstance(e.get("symbol"), str) or not isinstance(e.get("source"), str) or not e["source"].strip():
            raise ValueError("Missing symbol/source")
        at = _instant(e.get("at"))
        if e["symbol"].upper().strip() == symbol:
            timeline.append((at, e))
    timeline.sort(key=lambda x: x[0])
    first = {kind: next((t.isoformat() for t,e in timeline if e["kind"] == kind), None)
             for kind in VALID_KINDS}
    if first["trade"]:
        status = "broker_trade_in_evidence"
    elif first["decision"]:
        status = "decision_but_no_trade_in_evidence"
    elif first["candidate"]:
        status = "candidate_but_no_decision_in_evidence"
    elif first["source_row"]:
        status = "ingested_but_no_candidate_in_evidence"
    else:
        status = "no_ingestion_evidence"
    threshold = _instant(major_move_at) if major_move_at is not None else None
    first_candidate = _instant(first["candidate"]) if first["candidate"] else None
    early = None if threshold is None or first_candidate is None else first_candidate < threshold
    return {
        "symbol": symbol, "identity_verified": bool(identity_verified),
        "instrument_type": instrument_type or "unresolved",
        "status": status, "first_seen_utc": first,
        "major_move_at_utc": threshold.isoformat() if threshold else None,
        "candidate_before_major_move": early,
        "evidence_events": len(timeline),
        "caveat": "Missing scan logs do not establish a missed opportunity.",
    }

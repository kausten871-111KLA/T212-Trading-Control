"""Advisory evidence-quality annotations for saved research-role outputs.

Never blocks, routes or executes an order and never mutates original decisions.
All cited catalyst text must be separately verified before considered a fact.
"""
from __future__ import annotations
import re

def assess_decision(row, observation):
    ticker=row.get("ticker")
    if ticker != observation.get("ticker"):
        raise ValueError("decision/evidence mismatch")
    reasons=[]
    fields=["price","bid","ask","exchange","vwap","rvol"]
    for name in fields:
        if observation.get(name) is None:
            reasons.append("missing_"+name)
    if observation.get("stale"):
        reasons.append("stale_observation")
    spread=observation.get("spread_pct")
    if spread is not None:
        reasons.append("reported_spread_pct_"+format(float(spread),".2f"))
    remarks="\n".join(str(row.get(k) or "") for k in ("thesis","bull_case","bear_case"))
    # Keywords are audit leads ONLY, not proof of an invented claim.
    signatures={
        "institutional_activity_claim":r"\binstitutional (interest|buying|demand)\b",
        "unverified_catalyst_claim":r"\b(FDA|clinical data|merger rumours?|M&A rumors?)\b",
        "news_absence_claim":r"\b(no negative news|absence of negative news)\b",
        "unsupported_intraday_claim":r"\b(sustained intraday|intraday surge|confirmed intraday)\b",
        "spread_description":r"\b(narrow spread|tight spread|relatively narrow)\b",
    }
    for label,pattern in signatures.items():
        if re.search(pattern,remarks,flags=re.IGNORECASE):
            reasons.append("review_"+label)
    return {
        "ticker":ticker,
        "action":row.get("action"),
        "quote_verified":False,
        "catalyst_verified":False,
        "flags":sorted(set(reasons)),
        "research_only":True,
        "action_changed":False,
    }

def review_fixture(evidence, decisions):
    by_ticker={r["ticker"]:r for r in evidence["candidates"]}
    if len(by_ticker)!=len(evidence["candidates"]):
        raise ValueError("duplicate evidence tickers")
    seen=set()
    out=[]
    for r in decisions:
        name=r.get("ticker")
        if name not in by_ticker or name in seen:
            raise ValueError("unsupported or duplicate decision ticker")
        seen.add(name)
        out.append(assess_decision(r,by_ticker[name]))
    return out

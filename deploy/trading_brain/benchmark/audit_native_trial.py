"""Evidence-quality audit for identical-input baseline and native TradingAgents.

Produces analytical annotations ONLY. No broker calls, portfolio limits, or
automated trading rules. Regex findings are review flags, not factual proofs of
misconduct or hallucination.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re

from trading_brain_benchmark import (
    fingerprint, load_fixture, observation_only, validate_decisions,
    compare,
)

CONTEXT_PATTERNS = {
    "unverified_institutional_flow": r"(?:institutional interest|institutional buying|institutional demand)",
    "unverified_intraday_path": r"(?:intraday surge|sustained price action|sustained intraday)",
    "unverified_news_absence": r"(?:absence of negative news|no negative news)",
    "unsupported_bid_as_support": r"(?:bid price, representing a critical support level|bid (?:as|is) (?:a|the) support)",
    "unverified_clinical_catalyst": r"(?:FDA update|clinical data|M&A rumors)",
    "spread_called_narrow": r"(?:relatively narrow spread|tight spread|narrow spread)",
}
PROMOTING_TERMS = frozenset({"BUY", "SELL"})


def audit(fixture: Path, baseline_file: Path, challenger_file: Path) -> dict:
    evidence=observation_only(load_fixture(fixture))
    baseline=validate_decisions(baseline_file,evidence)
    challenger=validate_decisions(challenger_file,evidence)
    if challenger.get("mocked") is not False:
        raise ValueError("A real-model comparison requires mocked=false")
    if challenger.get("model_calls") != len(challenger["decisions"])*3:
        raise ValueError("Expected exactly 3 native model roles per symbol")
    if challenger.get("broker_orders") != 0:
        raise ValueError("Research should not submit orders")

    symbols={x["ticker"]:x for x in evidence["candidates"]}
    prior={x["ticker"]:x for x in baseline["decisions"]}
    findings=[]
    for row in challenger["decisions"]:
        symbol=row["ticker"]
        raw=symbols[symbol]
        original=prior.get(symbol)
        # Inspect only trader's final thesis, not the debates: bull/bear output
        # is argumentative by design, while trader conclusion is actionable.
        text=row.get("thesis","")
        matches=[
            {"type":name, "fragment":m.group(0)}
            for name,pattern in CONTEXT_PATTERNS.items()
            if (m:=re.search(pattern,text,flags=re.IGNORECASE))
        ]
        annotations=[]
        if raw["spread_pct"] is not None and raw["spread_pct"]>=20:
            annotations.append("quoted_spread_exceeds_20pct")
        if raw["bid"] is not None and raw["ask"] is not None and raw["price"] is not None:
            if raw["price"] < raw["bid"] or raw["price"] > raw["ask"]:
                annotations.append("reported_last_price_outside_bid_ask")
        if raw["exchange"] is None:
            annotations.append("exchange_unverified")
        if raw["rvol"] is None:
            annotations.append("relative_volume_missing")
        if raw["vwap"] is None:
            annotations.append("vwap_missing")
        if raw["catalyst"] and raw["catalyst"].lower() not in {"unknown","most-active"}:
            annotations.append("catalyst_text_is_unverified_hypothesis")
        if row["action"] in PROMOTING_TERMS:
            if raw["spread_pct"] is not None and raw["spread_pct"]>=20:
                annotations.append("action_buy_sell_on_very_wide_reported_spread")
            if raw["price"] is None or raw["bid"] is None or raw["ask"] is None:
                annotations.append("action_buy_sell_without_complete_pricing")
            if raw["exchange"] is None:
                annotations.append("action_buy_sell_without_verified_exchange")
        if "spread_called_narrow" in {m["type"] for m in matches} and (raw.get("spread_pct") or 0)>=20:
            annotations.append("language_calls_wide_spread_narrow")
        if "unverified_intraday_path" in {m["type"] for m in matches}:
            annotations.append("intraday_path_not_supplied")
        if "unverified_news_absence" in {m["type"] for m in matches}:
            annotations.append("absence_of_news_cannot_be_inferred")
        if "unverified_institutional_flow" in {m["type"] for m in matches}:
            annotations.append("institutional_activity_not_supplied")
        if "unsupported_bid_as_support" in {m["type"] for m in matches}:
            annotations.append("bid_price_does_not_establish_support")
        if "unverified_clinical_catalyst" in {m["type"] for m in matches}:
            annotations.append("illustrative_news_catalyst_not_verified")
        # These percentages concern ONLY the stale reported quote/last price,
        # not current order book conditions or actual trading P&L.
        quote_exposure=None
        if raw["price"] and raw["ask"] and raw["bid"]:
            quote_exposure={
                "reported_last_price":raw["price"],
                "reported_bid":raw["bid"],
                "reported_ask":raw["ask"],
                "ask_above_reported_last_pct":round(100*(raw["ask"]/raw["price"]-1),2),
                "cross_spread_ask_to_bid_loss_pct":round(100*(1-raw["bid"]/raw["ask"]),2),
            }
        findings.append({
            "ticker":symbol,
            "baseline_action":original["action"] if original else None,
            "tradingagents_action":row["action"],
            "source_spread_pct":raw.get("spread_pct"),
            "source_stale_flag":raw.get("stale"),
            "matched_language_patterns":matches,
            "evidence_quality_flags":sorted(set(annotations)),
            "quoted_execution_math_not_trade_result":quote_exposure,
        })
    diffs=compare(baseline,challenger)
    return {
        "dataset_id":evidence["dataset_id"],
        "evidence_sha256":fingerprint(evidence),
        "evaluated_at_utc":datetime.now(timezone.utc).isoformat(),
        "trial": {
            "real_model_calls":challenger.get("model_calls"),
            "model":challenger.get("model"),
            "native_nodes":challenger.get("engine"),
            "full_graph":False,
            "paid_api_spend_verified":False,
            "broker_orders":challenger.get("broker_orders"),
        },
        "comparison":diffs,
        "findings":findings,
        "conclusion":"Research comparison only. Flagged statements require evidence review. No trading performance improvement established.",
        "automatic_strategy_restrictions_added":False,
    }


def main():
    p=argparse.ArgumentParser()
    p.add_argument("fixture",type=Path)
    p.add_argument("baseline",type=Path)
    p.add_argument("challenger",type=Path)
    p.add_argument("--output",required=True,type=Path)
    args=p.parse_args()
    result=audit(args.fixture,args.baseline,args.challenger)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print("TRADING_BRAIN_EVIDENCE_AUDIT_PASS", json.dumps({
        "trial_symbols":len(result["findings"]),
        "actions_changed":len(result["comparison"]["actions_changed"]),
        "symbols_with_evidence_quality_flags":sum(bool(x["evidence_quality_flags"]) for x in result["findings"]),
        "output":str(args.output)
    },sort_keys=True))

if __name__=="__main__":
    main()

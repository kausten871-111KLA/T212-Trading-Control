"""Replay the real three-symbol research run in an isolated research-only lab.

No inference, HTTP, broker access or scheduled execution. Never claims a
forecast is an actual fill or that archived quotes are still executable.
"""
from __future__ import annotations
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

BENCHMARK_FOLDER=Path(__file__).resolve().parent.parent / "benchmark"
if str(BENCHMARK_FOLDER) not in sys.path:
    sys.path.insert(0,str(BENCHMARK_FOLDER))
from trading_brain_benchmark import fingerprint, observation_only, load_fixture, validate_decisions

from quote_economics import quote_economics
from evidence_review import review_fixture
from finmem_research import connect, record_decision, retrieve
from momentum_features import analyse_bars


def replay(fixture_file, baseline_file, native_file, *, sqlite_path, as_of_utc):
    fixture=load_fixture(Path(fixture_file))
    evidence=observation_only(fixture)
    baseline=json.loads(Path(baseline_file).read_text(encoding="utf-8"))
    native=json.loads(Path(native_file).read_text(encoding="utf-8"))
    if native.get("mocked") is not False or native.get("model_calls")!=9:
        raise ValueError("Expected real 3-symbol native role trial, exactly nine calls")
    expected=fingerprint(evidence)
    if baseline.get("evidence_sha256")!=expected or native.get("evidence_sha256")!=expected:
        raise ValueError("Evidence snapshots differ from original frozen data")
    if native.get("dataset_id")!=fixture["dataset_id"] or baseline.get("dataset_id")!=fixture["dataset_id"]:
        raise ValueError("Dataset identity changed")
    try:
        validate_decisions(Path(baseline_file),evidence)
        validate_decisions(Path(native_file),evidence)
    except (AssertionError,KeyError,TypeError) as exc:
        raise ValueError("Benchmark schema validation failed") from exc
    lookup={x["ticker"]:x for x in fixture["candidates"]}
    previous={x["ticker"]:x for x in baseline["decisions"]}
    review=review_fixture(fixture,native["decisions"])
    db=connect(sqlite_path)
    rows=[]
    try:
        assessment=native.get("assessed_at_utc")
        if not assessment:
            raise ValueError("Native decision timestamp absent")
        for dec,audit in zip(native["decisions"],review):
            ticker=dec["ticker"]
            observation=lookup[ticker]
            price_analysis=quote_economics(observation,quantity=100)
            # Frozen EOD contains zero intraday bars; return explicit Nones.
            bar_analysis=analyse_bars([],as_of_utc=fixture["observation_timestamp_utc"])
            record_decision(db,decision_id="tradingagents-real-20261020-"+ticker,
                ticker=ticker,observed_at_utc=assessment,
                phase="research",thesis=dec["thesis"],
                evidence_sha256=native["evidence_sha256"])
            rows.append({
                "ticker":ticker,
                "baseline_action":previous[ticker]["action"],
                "challenger_action":dec["action"],
                "original_action_preserved":True,
                "quote_costs_scenario_100_shares":price_analysis,
                "momentum_from_available_bars":bar_analysis,
                "advisory_evidence_review":audit,
                "model_reasoning_still_needs_independent_outcome_validation":True,
            })
        mem=retrieve(db,as_of_utc=as_of_utc)
        return {
            "dataset_id":native["dataset_id"],
            "evidence_sha256":native["evidence_sha256"],
            "model_calls_previous_trial":9,
            "model_calls_this_replay":0,
            "broker_orders_this_replay":0,
            "trades_executed_from_research":False,
            "rows":rows,
            "memory_decisions_visible_as_of":len(mem),
            "memory_outcomes_visible_as_of":sum(x["outcome"] is not None for x in mem),
            "not_a_live_market_signal":True,
        }
    finally:
        db.close()

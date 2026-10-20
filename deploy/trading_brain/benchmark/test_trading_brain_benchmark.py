import json
from pathlib import Path
import pytest

from trading_brain_benchmark import (
    load_fixture, audit, observation_only, fingerprint,
    make_prompt, validate_decisions, compare,
)

FIXTURE = Path(__file__).with_name("alpaca_eod_20261020_20.json")


def test_source_coverage_exact():
    data = load_fixture(FIXTURE)
    summary = audit(data)
    assert summary["candidates"] == 20
    assert summary["price_available"] == 11
    assert summary["bid_ask_available"] == 7
    assert summary["vwap_available"] == 0
    assert summary["rvol_available"] == 0
    assert summary["exchange_available"] == 0
    assert summary["quotes_with_spread_over_20pct"] == [
        "MYGN", "WORX", "AIXI", "PRSO", "FRTT", "AIMDW"
    ]


def test_no_prior_rejections_leak_into_model_evidence():
    data = load_fixture(FIXTURE)
    assert any(x["flag"].startswith("REJECT") for x in data["candidates"])
    obs = observation_only(data)
    assert all("flag" not in x for x in obs["candidates"])
    assert obs["limitations"]["catalyst_descriptions"].endswith("not verified external news")


def test_identical_evidence_for_both_roles():
    obs = observation_only(load_fixture(FIXTURE))
    sha = fingerprint(obs)
    left = make_prompt(obs, mode="baseline")
    right = make_prompt(obs, mode="debate")
    assert left.count(sha) == 1 and right.count(sha) == 1
    assert left.split("FROZEN_DATASET_JSON:\n")[1].split("\n\nReturn only")[0] == (
        right.split("FROZEN_DATASET_JSON:\n")[1].split("\n\nReturn only")[0])
    assert "full LangGraph TradingAgents graph" in right


def test_model_decision_schema_and_comparison(tmp_path):
    obs = observation_only(load_fixture(FIXTURE))
    sha = fingerprint(obs)
    row = dict(
        ticker="BRZE", action="WAIT",
        thesis="Unverified acquisition hypothesis",
        bull_case="Liquid published bid/ask",
        bear_case="Deal terms not verified",
        missing_evidence=["Deal announcement", "current quotes"],
        evidence_tickers=["BRZE"],
    )
    p1=tmp_path/"one.json"
    p2=tmp_path/"two.json"
    base={"dataset_id":obs["dataset_id"],"evidence_sha256":sha,
          "decisions":[row],"assessed_at_utc":None}
    challenger={**base, "decisions":[{**row,"action":"RESEARCH"}]}
    p1.write_text(json.dumps(base))
    p2.write_text(json.dumps(challenger))
    left=validate_decisions(p1,obs)
    right=validate_decisions(p2,obs)
    result=compare(left,right)
    assert result["actions_changed"] == [
        {"ticker":"BRZE","baseline":"WAIT","challenger":"RESEARCH"}
    ]
    assert result["causal_improvement_proven"] is False


def test_rejects_hallucinated_symbol(tmp_path):
    obs=observation_only(load_fixture(FIXTURE))
    p=tmp_path/"bad.json"
    p.write_text(json.dumps({
        "dataset_id":obs["dataset_id"],
        "evidence_sha256":fingerprint(obs),
        "decisions":[{
            "ticker":"FAKE999","action":"BUY",
            "thesis":"none","bull_case":"none","bear_case":"none",
            "missing_evidence":[],"evidence_tickers":["FAKE999"]
        }]
    }))
    with pytest.raises(AssertionError):
        validate_decisions(p,obs)


def test_no_executable_automation_or_broker_import():
    text=Path(__file__).with_name("trading_brain_benchmark.py").read_text()
    assert "subprocess" not in text
    assert "requests" not in text
    assert "trading_212_demo_gateway" not in text
    assert "openai import" not in text

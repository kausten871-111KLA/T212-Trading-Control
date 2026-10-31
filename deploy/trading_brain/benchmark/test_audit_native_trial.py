"""Evidence annotation regression tests, no broker or model network."""
from pathlib import Path
import json
import pytest
from audit_native_trial import audit

ROOT=Path(__file__).parent
FIXTURE=ROOT/"alpaca_eod_20261020_20.json"
BASELINE=ROOT/"results/deepseek_baseline_validated_20261020.json"
CHALLENGER=ROOT/"results/tradingagents_native_real_3symbols.json"

@pytest.fixture(scope="module")
def report():
    return audit(FIXTURE,BASELINE,CHALLENGER)

def test_trial_three_real_roles(report):
    assert report["trial"]["real_model_calls"]==9
    assert report["trial"]["broker_orders"]==0
    assert report["trial"]["full_graph"] is False
    assert set(x["ticker"] for x in report["findings"])=={"BRZE","MYGN","PRSO"}
    assert report["automatic_strategy_restrictions_added"] is False

def test_changed_actions_preserved(report):
    assert {x["ticker"]:(x["baseline_action"],x["tradingagents_action"])
            for x in report["findings"]}=={
                "BRZE":("WAIT","HOLD"),
                "MYGN":("WAIT","BUY"),
                "PRSO":("WAIT","HOLD")}

def test_mygn_buy_has_quote_quality_flags(report):
    x=next(x for x in report["findings"] if x["ticker"]=="MYGN")
    assert x["source_spread_pct"]==28.73
    assert "action_buy_sell_on_very_wide_reported_spread" in x["evidence_quality_flags"]
    assert "institutional_activity_not_supplied" in x["evidence_quality_flags"]
    assert "intraday_path_not_supplied" in x["evidence_quality_flags"]
    assert "absence_of_news_cannot_be_inferred" in x["evidence_quality_flags"]
    assert x["quoted_execution_math_not_trade_result"]["ask_above_reported_last_pct"]>14

def test_prso_narrow_spread_contradiction(report):
    x=next(x for x in report["findings"] if x["ticker"]=="PRSO")
    assert x["source_spread_pct"]==27.09
    assert "language_calls_wide_spread_narrow" in x["evidence_quality_flags"]

def test_never_claims_backtested_pnl(report):
    assert report["comparison"]["causal_improvement_proven"] is False
    assert report["trial"]["paid_api_spend_verified"] is False
    assert report["automatic_strategy_restrictions_added"] is False

def test_report_does_not_embed_secret_values(report):
    text=json.dumps(report)
    assert "sk-or-" not in text
    assert "OPENROUTER_API_KEY=" not in text

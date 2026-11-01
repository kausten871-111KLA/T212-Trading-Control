"""Use TradingAgents' NATIVE bull/bear/trader functions on a frozen dataset.

Defaults to an offline mocked dry run. Real mode requires an explicit
--allow-model-calls flag and OPENROUTER_API_KEY from a private runtime
environment. No Trading212/Alpaca tools are imported or broker orders sent.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re

from langchain_core.messages import AIMessage
from tradingagents.agents.researchers.bull_researcher import create_bull_researcher
from tradingagents.agents.researchers.bear_researcher import create_bear_researcher
from tradingagents.agents.trader.trader import create_trader
from tradingagents.llm_clients.factory import create_llm_client

from trading_brain_benchmark import load_fixture, observation_only, fingerprint

DEFAULT_TICKERS = ("BRZE", "MYGN", "PRSO")
MAX_SYMBOLS = 3
MAX_MODEL_CALLS = 9
MAX_OUTPUT_TOKENS_PER_CALL = 550


class BudgetedLLM:
    def __init__(self, model=None, *, allow_model_calls=False):
        self.model = model
        self.allow_model_calls = allow_model_calls
        self.calls = 0

    def with_structured_output(self, _schema):
        # Avoid one structured-output call + an unplanned free-text retry.
        raise NotImplementedError("Use exactly one bounded free-text model call per role.")

    def invoke(self, prompt):
        if self.calls >= MAX_MODEL_CALLS:
            raise RuntimeError("Bounded model-call budget exhausted")
        self.calls += 1
        if not self.allow_model_calls:
            if isinstance(prompt,str) and "Bull Analyst" in prompt:
                return AIMessage(content="Mock bull: upside requires real quotes and catalyst checks.")
            if isinstance(prompt,str) and "Bear Analyst" in prompt:
                return AIMessage(content="Mock bear: spread and stale-data uncertainty.")
            return AIMessage(content="Hold\nMock trader: research only; no orders.")
        return self.model.invoke(prompt)


def make_state(row, evidence):
    return {
        "company_of_interest": row["ticker"],
        "instrument_context": (
            "This instrument is exactly " + row["ticker"] +
            ". Exchange and broker instrument mapping not verified. "
            "Use only the frozen historical data provided here."
        ),
        "asset_type": "stock",
        "trade_date": "2026-10-20",
        "market_report": json.dumps({
            "dataset_id":evidence["dataset_id"],
            "observation_timestamp_utc":evidence["observation_timestamp_utc"],
            "ticker":row["ticker"],
            "facts":row,
            "data_quality_limitations":evidence["limitations"],
        },sort_keys=True),
        "sentiment_report":"",
        "news_report":"",
        "fundamentals_report":"",
        "investment_debate_state":{
            "history":"","bull_history":"","bear_history":"",
            "current_response":"","count":0,
        },
        "investment_plan":"",
    }


def parse_action(plan):
    match=re.search(r"(?im)^(?:\s*[-*]?\s*)?(?:\*\*Action\*\*:\s*)?(Buy|Sell|Hold)\b",plan)
    return match.group(1).upper() if match else "RESEARCH"


def produce(fixture, *, tickers=DEFAULT_TICKERS, allow_model_calls=False):
    data=observation_only(load_fixture(fixture))
    known={r["ticker"]:r for r in data["candidates"]}
    assert len(tickers)>0 and len(tickers)<=MAX_SYMBOLS
    assert len(set(tickers))==len(tickers)
    assert set(tickers)<=set(known)
    if allow_model_calls:
        if not os.environ.get("OPENROUTER_API_KEY"):
            secret=Path("/run/secrets/openrouter")
            if secret.is_file():
                value=secret.read_text(encoding="utf-8").strip()
                if len(value) >= 12 and value.isascii() and not any(x.isspace() for x in value):
                    os.environ["OPENROUTER_API_KEY"]=value
        if not os.environ.get("OPENROUTER_API_KEY"):
            raise RuntimeError("OPENROUTER_KEY_NOT_CONFIGURED")
        client=create_llm_client("openrouter","deepseek/deepseek-chat",max_retries=0)
        model=client.get_llm().bind(max_tokens=MAX_OUTPUT_TOKENS_PER_CALL)
    else:
        model=None
    llm=BudgetedLLM(model,allow_model_calls=allow_model_calls)
    bull=create_bull_researcher(llm)
    bear=create_bear_researcher(llm)
    trader=create_trader(llm)
    decisions=[]
    for ticker in tickers:
        row=known[ticker]
        state=make_state(row,data)
        bull_result=bull(state)
        bull_text=bull_result["investment_debate_state"]["current_response"]
        state.update(bull_result)
        bear_result=bear(state)
        bear_text=bear_result["investment_debate_state"]["current_response"]
        state.update(bear_result)
        state["investment_plan"]=state["investment_debate_state"]["history"]
        plan=trader(state)["trader_investment_plan"]
        missing=[name for name in ("price","change_pct","bid","ask","rvol","vwap","exchange")
                 if row.get(name) is None]
        if row["stale"]: missing.append("Fresh timestamped quote")
        missing+=["Independently verified catalyst/news",
                  "T212 symbol and current executable quote"]
        decisions.append({
            "ticker":ticker,
            "action":parse_action(plan),
            "thesis":plan,
            "bull_case":bull_text,
            "bear_case":bear_text,
            "missing_evidence":missing,
            "evidence_tickers":[ticker],
        })
    assert llm.calls==3*len(tickers)
    return {
        "dataset_id":data["dataset_id"],
        "evidence_sha256":fingerprint(data),
        "assessed_at_utc":datetime.now(timezone.utc).isoformat(),
        "decisions":decisions,
        "engine":"Native TradingAgents bull/bear/trader nodes; NOT entire LangGraph graph",
        "mocked":not allow_model_calls,
        "model_calls":llm.calls,
        "model":"deepseek/deepseek-chat" if allow_model_calls else "deterministic mock",
        "broker_orders":0,
        "market_data_queries":0,
        "not_investment_execution":True,
    }


def main():
    p=argparse.ArgumentParser()
    p.add_argument("fixture",type=Path)
    p.add_argument("--tickers",nargs="+",default=list(DEFAULT_TICKERS))
    p.add_argument("--allow-model-calls",action="store_true")
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    result=produce(a.fixture,tickers=tuple(a.tickers),allow_model_calls=a.allow_model_calls)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n")
    print("NATIVE_TRADINGAGENTS_RESEARCH_PASS",json.dumps({
        "tickers":a.tickers,"model_calls":result["model_calls"],
        "mocked":result["mocked"],"broker_orders":0,
        "evidence_sha256":result["evidence_sha256"],
        "output":str(a.output),
    },sort_keys=True))


if __name__=="__main__":
    main()

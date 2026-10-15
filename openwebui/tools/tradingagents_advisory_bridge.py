"""Optional TradingAgents to DeepSeek research-brief translator.

Stage 1 of GitHub issue #18. Does not connect to a broker or submit orders.
TradingAgents must be separately installed/configured before remote inference
will occur. The DeepSeek controller decides how to use the resulting evidence.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from typing import Any, Callable, Mapping

SYMBOL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,31}\Z")
REPORT_FIELDS = ("market_report", "sentiment_report", "news_report",
                 "fundamentals_report", "trader_investment_plan",
                 "investment_plan", "final_trade_decision")


class AdvisoryError(ValueError):
    pass


def as_text(value: Any) -> str:
    """Convert written research into data fields, never code/instructions."""
    if value is None:
        return ""
    return value.strip() if isinstance(value, str) else json.dumps(value, default=str, sort_keys=True)


def make_advisory(
    ticker: str, trade_date: str, final_state: Mapping[str, Any],
    proposed_decision: Any, *,
    upstream_revision: str = "UNPINNED",
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    """Create a stable, broker-independent evidence handoff for DeepSeek.

    Upstream output is untrusted research, not authorization to place T212 orders.
    Historical date correctness also depends on the underlying TradingAgents
    provider supplying point-in-time data; this adapter does not certify it.
    """
    if not isinstance(ticker, str) or not SYMBOL.fullmatch(ticker):
        raise AdvisoryError("A valid plain ticker is required")
    if not isinstance(trade_date, str):
        raise AdvisoryError("trade_date must be YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(trade_date)
    except ValueError as exc:
        raise AdvisoryError("trade_date must be YYYY-MM-DD") from exc
    if parsed.isoformat() != trade_date or parsed > datetime.now(timezone.utc).date():
        raise AdvisoryError("trade_date must be canonical and not in the future")
    if not isinstance(final_state, Mapping):
        raise AdvisoryError("TradingAgents final_state must be a mapping")
    reports = {key: as_text(final_state.get(key)) for key in REPORT_FIELDS}
    if not reports["final_trade_decision"]:
        reports["final_trade_decision"] = as_text(proposed_decision)
    generated = generated_at_utc or datetime.now(timezone.utc).isoformat()
    identity = json.dumps([ticker.upper(), trade_date, reports, upstream_revision],
                          sort_keys=True, ensure_ascii=True)
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    return {
        "type": "external_research_advisory",
        "source": "TauricResearch/TradingAgents",
        "source_revision": upstream_revision,
        "advisory_id": "ta-" + digest,
        "symbol": ticker.upper(),
        "analysis_date": trade_date,
        "generated_at_utc": generated,
        "reports": reports,
        "claim_status": "unverified_external_research",
        "deepseek_role": "sole trading decision-maker",
        "execution_authority": False,
        "trading212_broker_calls": 0,
        "limitations": [
            "Source news, prices and as-of integrity require independent verification.",
            "Backtest performance cannot establish future trading profitability.",
            "A TradingAgents recommendation does not constitute a broker instruction.",
        ],
    }


def research_once(
    ticker: str, trade_date: str, *,
    config: dict[str, Any] | None = None,
    selected_analysts: tuple[str, ...] = ("market", "news"),
    graph_factory: Callable[..., Any] | None = None,
    upstream_revision: str = "UNPINNED",
) -> dict[str, Any]:
    """Optionally invoke TradingAgents. No imports, models or costs before call.

    The caller supplies its own LLM provider config and market-data credentials
    to TradingAgents; T212 keys are neither required nor accessed here.
    """
    if graph_factory is None:
        try:
            from tradingagents.graph.trading_graph import TradingAgentsGraph
        except ImportError as exc:
            raise AdvisoryError("TradingAgents is not installed in this research environment") from exc
        graph_factory = TradingAgentsGraph
    # Validate user input *before* allowing model construction.
    make_advisory(ticker,trade_date,{},None,upstream_revision=upstream_revision,
                  generated_at_utc="not-started")
    kwargs = {"selected_analysts": selected_analysts, "debug": False}
    if config is not None:
        kwargs["config"] = config
    graph = graph_factory(**kwargs)
    final_state, decision = graph.propagate(ticker.upper(), trade_date)
    return make_advisory(ticker,trade_date,final_state,decision,
                         upstream_revision=upstream_revision)

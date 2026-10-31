"""Frozen, point-in-time trading research benchmark.

Never imports a broker, network client or model SDK. All decisions are supplied
later by actual models; this module does NOT pretend to be TradingAgents.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path

ACTIONS = frozenset(("BUY", "SELL", "HOLD", "WAIT", "RESEARCH"))
REQUIRED = ("ticker", "action", "thesis", "bull_case", "bear_case",
            "missing_evidence", "evidence_tickers")
PRIMARY_FIELDS = ("ticker", "exchange", "price", "change_pct", "day_volume",
                  "rvol", "vwap", "bid", "ask", "spread_pct", "stale", "catalyst")


def load_fixture(path: Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    assert isinstance(data.get("candidates"), list), "Missing candidates"
    tickers = [r["ticker"] for r in data["candidates"]]
    assert len(tickers) == 20 and len(set(tickers)) == 20, "Expected 20 unique tickers"
    for row in data["candidates"]:
        assert all(key in row for key in PRIMARY_FIELDS), row.get("ticker")
        assert isinstance(row["day_volume"], int) and row["day_volume"] >= 0
        quote = row["bid"] is not None and row["ask"] is not None
        if quote:
            assert 0 < row["bid"] <= row["ask"], row["ticker"]
            calc = 200 * (row["ask"] - row["bid"]) / (row["ask"] + row["bid"])
            assert abs(calc - row["spread_pct"]) < 0.06, (
                row["ticker"], calc, row["spread_pct"])
        else:
            assert row["bid"] is None and row["ask"] is None
            assert row["spread_pct"] is None
    when = datetime.fromisoformat(data["observation_timestamp_utc"].replace("Z", "+00:00"))
    assert when.tzinfo is not None
    return data


def audit(data: dict) -> dict:
    rows = data["candidates"]
    quote = [x for x in rows if x["bid"] is not None and x["ask"] is not None]
    return {
        "dataset_id": data["dataset_id"],
        "observation_timestamp_utc": data["observation_timestamp_utc"],
        "candidates": len(rows),
        "price_available": sum(x["price"] is not None for x in rows),
        "bid_ask_available": len(quote),
        "vwap_available": sum(x["vwap"] is not None for x in rows),
        "rvol_available": sum(x["rvol"] is not None for x in rows),
        "exchange_available": sum(x["exchange"] is not None for x in rows),
        "catalyst_news_verified": 0,
        "stale_flag_true": [x["ticker"] for x in rows if x["stale"]],
        "no_quote_timestamp_provided": len(rows),
        "quotes_with_spread_over_20pct": [x["ticker"] for x in quote if x["spread_pct"] > 20],
        "eod_only": True,
        "broker_executable_quotes_confirmed": 0,
        "note": "Source flags are prior DeepSeek opinions, not labels used to train or prompt the challenger.",
    }


def observation_only(data: dict) -> dict:
    """Same evidence for both prompts; previous WATCH/REJECT decisions withheld."""
    return {
        "dataset_id": data["dataset_id"],
        "observation_timestamp_utc": data["observation_timestamp_utc"],
        "market_state": data["market_state"],
        "data_source": data["data_source"],
        "provenance": data["provenance"],
        "limitations": {
            "quote_timestamps_missing": True,
            "market_closed": True,
            "catalyst_descriptions": "User-supplied hypotheses, not verified external news",
            "no_verified_exchange": True,
            "no_verified_broker_instrument_mapping": True,
            "not_executable_prices": True,
        },
        "candidates": [
            {key: value for key, value in row.items() if key in PRIMARY_FIELDS}
            for row in data["candidates"]
        ],
    }


def fingerprint(evidence: dict) -> str:
    return hashlib.sha256(
        json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        .encode("utf-8")
    ).hexdigest()


SCHEMA_NOTE = """Return only one JSON object with:
- dataset_id (exact value supplied)
- evidence_sha256 (exact value supplied)
- decisions: array of up to 20 objects, each with ticker, action
  (BUY/SELL/HOLD/WAIT/RESEARCH), thesis, bull_case, bear_case,
  missing_evidence (array of strings), evidence_tickers (array).
- assessed_at_utc (your actual assessment time or null).
Provide explicit reasons for each action and uncertainty. BUY/SELL are research
opinions ONLY in this offline task, not broker instructions. Do not execute
orders, call tools, invent indicators/news, or change existing automations.
"""


BASELINE = """You are the user's existing DeepSeek Trading Operations decision specialist.
Apply the trading principles already established in your current model context.
Use ONLY the attached frozen snapshot. Clearly distinguish data uncertainty
from a strategy reason to avoid a trade. Price below $1, large percentage gains,
or leveraged instruments are NOT automatic exclusions; evaluate evidence.
Evaluate up to 20 tickers and return the exact JSON contract.
"""


DEBATE = """You are conducting a TradingAgents-style independent multi-agent
deliberation. For every assessed ticker, reason in three explicit roles:
(1) bullish analyst: strongest evidence-backed opportunity,
(2) bearish analyst: strongest evidence-backed counterargument,
(3) trader: weigh both and choose a research action.
Use ONLY the same attached frozen snapshot. No historical labels and no
new data calls. Price below $1, large gains and leveraged instruments are NOT
automatic exclusions; consider opportunity and uncertainty independently.
Return the exact JSON contract. This is a prompt-level TradingAgents-style
benchmark, NOT proof of executing the full LangGraph TradingAgents graph.
"""


def make_prompt(evidence: dict, *, mode: str) -> str:
    assert mode in ("baseline", "debate")
    guide = BASELINE if mode == "baseline" else DEBATE
    encoded = json.dumps(evidence, indent=2, ensure_ascii=False, sort_keys=True)
    return (
        "# Frozen Trading Brain benchmark\n\n" + guide +
        "\nEVIDENCE_SHA256 = " + fingerprint(evidence) + "\n\n" +
        "FROZEN_DATASET_JSON:\n" + encoded + "\n\n" +
        SCHEMA_NOTE
    )


def validate_decisions(path: Path, evidence: dict) -> dict:
    parsed = json.loads(Path(path).read_text(encoding="utf-8"))
    assert parsed["dataset_id"] == evidence["dataset_id"]
    assert parsed["evidence_sha256"] == fingerprint(evidence)
    known = {x["ticker"] for x in evidence["candidates"]}
    assert isinstance(parsed["decisions"], list) and len(parsed["decisions"]) <= 20
    seen = set()
    for row in parsed["decisions"]:
        assert all(field in row for field in REQUIRED), row
        assert row["ticker"] in known and row["ticker"] not in seen
        assert row["action"] in ACTIONS
        assert isinstance(row["missing_evidence"], list)
        assert isinstance(row["evidence_tickers"], list)
        assert set(row["evidence_tickers"]) <= known
        for key in ("thesis", "bull_case", "bear_case"):
            assert isinstance(row[key], str)
        seen.add(row["ticker"])
    return parsed


def compare(baseline: dict, challenger: dict) -> dict:
    left = {x["ticker"]: x for x in baseline["decisions"]}
    right = {x["ticker"]: x for x in challenger["decisions"]}
    shared = set(left) & set(right)
    return {
        "baseline_assessed": len(left),
        "challenger_assessed": len(right),
        "overlap_count": len(shared),
        "actions_changed": [
            {"ticker": t, "baseline": left[t]["action"], "challenger": right[t]["action"]}
            for t in sorted(shared) if left[t]["action"] != right[t]["action"]
        ],
        "only_baseline": sorted(set(left)-shared),
        "only_challenger": sorted(set(right)-shared),
        "causal_improvement_proven": False,
        "note": "This compares reasoning/coverage only. P&L requires subsequent market data and broker receipts.",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("audit", "prompts", "compare"))
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--challenger", type=Path)
    args = parser.parse_args()
    data = load_fixture(args.fixture)
    if args.command == "audit":
        print(json.dumps(audit(data), indent=2))
    elif args.command == "prompts":
        assert args.output
        args.output.mkdir(parents=True, exist_ok=True)
        evidence = observation_only(data)
        for mode in ("baseline", "debate"):
            path = args.output / f"trading_brain_{mode}_20.md"
            path.write_text(make_prompt(evidence, mode=mode), encoding="utf-8")
            print("PROMPT", mode, str(path), "SHA256", fingerprint(evidence))
    else:
        assert args.baseline and args.challenger
        evidence = observation_only(data)
        results = compare(validate_decisions(args.baseline,evidence),
                          validate_decisions(args.challenger,evidence))
        print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()

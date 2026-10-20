# Frozen Trading Brain benchmark

You are conducting a TradingAgents-style independent multi-agent
deliberation. For every assessed ticker, reason in three explicit roles:
(1) bullish analyst: strongest evidence-backed opportunity,
(2) bearish analyst: strongest evidence-backed counterargument,
(3) trader: weigh both and choose a research action.
Use ONLY the same attached frozen snapshot. No historical labels and no
new data calls. Price below $1, large gains and leveraged instruments are NOT
automatic exclusions; consider opportunity and uncertainty independently.
Return the exact JSON contract. This is a prompt-level TradingAgents-style
benchmark, NOT proof of executing the full LangGraph TradingAgents graph.

EVIDENCE_SHA256 = cbf27160ec376c2355729d1f1eeb05e6a30082128eff2c46b99fa617f32c49d1

FROZEN_DATASET_JSON:
{
  "candidates": [
    {
      "ask": 45.56,
      "bid": 45.5,
      "catalyst": "Takeover gap (all-cash M&A; price pinned near deal terms — merger-arb, not momentum)",
      "change_pct": 51.7,
      "day_volume": 1779314,
      "exchange": null,
      "price": 45.57,
      "rvol": null,
      "spread_pct": 0.13,
      "stale": false,
      "ticker": "BRZE",
      "vwap": null
    },
    {
      "ask": 6.37,
      "bid": 4.77,
      "catalyst": "Catalyst gap (news-driven)",
      "change_pct": 31.4,
      "day_volume": 934853,
      "exchange": null,
      "price": 5.54,
      "rvol": null,
      "spread_pct": 28.73,
      "stale": false,
      "ticker": "MYGN",
      "vwap": null
    },
    {
      "ask": null,
      "bid": null,
      "catalyst": "IPO spike (wide/no clean quote)",
      "change_pct": 100.59,
      "day_volume": 175476,
      "exchange": null,
      "price": 6.84,
      "rvol": null,
      "spread_pct": null,
      "stale": false,
      "ticker": "SAIQ",
      "vwap": null
    },
    {
      "ask": null,
      "bid": null,
      "catalyst": "Unknown",
      "change_pct": 52.64,
      "day_volume": 2198,
      "exchange": null,
      "price": 6.93,
      "rvol": null,
      "spread_pct": null,
      "stale": false,
      "ticker": "ATGL",
      "vwap": null
    },
    {
      "ask": null,
      "bid": null,
      "catalyst": "Unknown",
      "change_pct": 47.4,
      "day_volume": 81450,
      "exchange": null,
      "price": 2.83,
      "rvol": null,
      "spread_pct": null,
      "stale": false,
      "ticker": "HOST",
      "vwap": null
    },
    {
      "ask": 4.22,
      "bid": 3.13,
      "catalyst": "Unknown",
      "change_pct": 36.57,
      "day_volume": 131459,
      "exchange": null,
      "price": 3.66,
      "rvol": null,
      "spread_pct": 29.66,
      "stale": false,
      "ticker": "WORX",
      "vwap": null
    },
    {
      "ask": 3.58,
      "bid": 2.64,
      "catalyst": "Unknown",
      "change_pct": 40.91,
      "day_volume": 272997,
      "exchange": null,
      "price": 3.1,
      "rvol": null,
      "spread_pct": 30.23,
      "stale": false,
      "ticker": "AIXI",
      "vwap": null
    },
    {
      "ask": 0.67,
      "bid": 0.51,
      "catalyst": "Unknown (sub-$1 pump)",
      "change_pct": 54.13,
      "day_volume": 553886,
      "exchange": null,
      "price": 0.59,
      "rvol": null,
      "spread_pct": 27.09,
      "stale": false,
      "ticker": "PRSO",
      "vwap": null
    },
    {
      "ask": null,
      "bid": null,
      "catalyst": "Unknown (sub-$1)",
      "change_pct": 32.14,
      "day_volume": 706177,
      "exchange": null,
      "price": 0.21,
      "rvol": null,
      "spread_pct": null,
      "stale": false,
      "ticker": "SAFX",
      "vwap": null
    },
    {
      "ask": 0.81,
      "bid": 0.61,
      "catalyst": "Unknown (penny pump, huge volume)",
      "change_pct": -6.58,
      "day_volume": 208847827,
      "exchange": null,
      "price": 0.71,
      "rvol": null,
      "spread_pct": 28.17,
      "stale": false,
      "ticker": "FRTT",
      "vwap": null
    },
    {
      "ask": null,
      "bid": null,
      "catalyst": "Most-active (regime/flow context, not a gap)",
      "change_pct": null,
      "day_volume": 79276021,
      "exchange": null,
      "price": null,
      "rvol": null,
      "spread_pct": null,
      "stale": false,
      "ticker": "NVDA",
      "vwap": null
    },
    {
      "ask": null,
      "bid": null,
      "catalyst": "Most-active",
      "change_pct": null,
      "day_volume": 82642905,
      "exchange": null,
      "price": null,
      "rvol": null,
      "spread_pct": null,
      "stale": false,
      "ticker": "INTC",
      "vwap": null
    },
    {
      "ask": null,
      "bid": null,
      "catalyst": "Most-active (AI/data-centre theme)",
      "change_pct": null,
      "day_volume": 93245051,
      "exchange": null,
      "price": null,
      "rvol": null,
      "spread_pct": null,
      "stale": false,
      "ticker": "CRWV",
      "vwap": null
    },
    {
      "ask": null,
      "bid": null,
      "catalyst": "Most-active (bitcoin miner)",
      "change_pct": null,
      "day_volume": 71916142,
      "exchange": null,
      "price": null,
      "rvol": null,
      "spread_pct": null,
      "stale": false,
      "ticker": "IREN",
      "vwap": null
    },
    {
      "ask": null,
      "bid": null,
      "catalyst": "Most-active",
      "change_pct": null,
      "day_volume": 71843890,
      "exchange": null,
      "price": null,
      "rvol": null,
      "spread_pct": null,
      "stale": false,
      "ticker": "NU",
      "vwap": null
    },
    {
      "ask": null,
      "bid": null,
      "catalyst": "Most-active (bitcoin ETF)",
      "change_pct": null,
      "day_volume": 71152736,
      "exchange": null,
      "price": null,
      "rvol": null,
      "spread_pct": null,
      "stale": false,
      "ticker": "BITO",
      "vwap": null
    },
    {
      "ask": null,
      "bid": null,
      "catalyst": "Most-active (leveraged ETP)",
      "change_pct": null,
      "day_volume": 96307258,
      "exchange": null,
      "price": null,
      "rvol": null,
      "spread_pct": null,
      "stale": false,
      "ticker": "SOXL",
      "vwap": null
    },
    {
      "ask": null,
      "bid": null,
      "catalyst": "Most-active (leveraged ETP)",
      "change_pct": null,
      "day_volume": 75077789,
      "exchange": null,
      "price": null,
      "rvol": null,
      "spread_pct": null,
      "stale": false,
      "ticker": "SOXS",
      "vwap": null
    },
    {
      "ask": null,
      "bid": null,
      "catalyst": "Most-active (leveraged ETP)",
      "change_pct": null,
      "day_volume": 72917741,
      "exchange": null,
      "price": null,
      "rvol": null,
      "spread_pct": null,
      "stale": false,
      "ticker": "MSTZ",
      "vwap": null
    },
    {
      "ask": 0.0893,
      "bid": 0.0409,
      "catalyst": "Warrant (symbol suffix W)",
      "change_pct": 111.31,
      "day_volume": 100,
      "exchange": null,
      "price": 0.0579,
      "rvol": null,
      "spread_pct": 74.35,
      "stale": true,
      "ticker": "AIMDW",
      "vwap": null
    }
  ],
  "data_source": "Alpaca (IEX feed, read-only) — top_movers + most_active + snapshots",
  "dataset_id": "alpaca_eod_2026-10-20_20_symbol_user_supplied",
  "limitations": {
    "catalyst_descriptions": "User-supplied hypotheses, not verified external news",
    "market_closed": true,
    "no_verified_broker_instrument_mapping": true,
    "no_verified_exchange": true,
    "not_executable_prices": true,
    "quote_timestamps_missing": true
  },
  "market_state": "CLOSED (next_open 2026-10-21T09:30:00-04:00)",
  "observation_timestamp_utc": "2026-10-20T21:40:00Z",
  "provenance": "User-pasted DeepSeek snapshot; raw vendor tool responses have not been independently re-fetched in this benchmark."
}

Return only one JSON object with:
- dataset_id (exact value supplied)
- evidence_sha256 (exact value supplied)
- decisions: array of up to 20 objects, each with ticker, action
  (BUY/SELL/HOLD/WAIT/RESEARCH), thesis, bull_case, bear_case,
  missing_evidence (array of strings), evidence_tickers (array).
- assessed_at_utc (your actual assessment time or null).
Provide explicit reasons for each action and uncertainty. BUY/SELL are research
opinions ONLY in this offline task, not broker instructions. Do not execute
orders, call tools, invent indicators/news, or change existing automations.

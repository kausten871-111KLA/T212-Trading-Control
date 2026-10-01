---
name: trading-decision-engine
description: Convert qualified opportunities into explicit DEMO trade actions using momentum, sentiment, risk, freshness, liquidity, spread and scenario validation.
---

# Trading Decision Engine

Apply freshness, momentum, liquidity, spread, volatility, T212 validity, catalyst surprise/pricing, confirmation/invalidation and dilution/manipulation checks.

Use S_trade = (0.6 * Sentiment + 0.4 * Momentum) * (1 - sigma / Confidence) only as a decision aid. It never overrides stale data, broker facts, liquidity/spread problems, invalid instruments or risk controls.

Output: exact T212 ticker; action BUY / HOLD / EXIT / NO TRADE; intended exposure; entry logic; target/exit; invalidation/stop; risks; evidence; rejection reason when applicable.

Never call T212 directly.

---
name: trading-decision-engine
description: Convert qualified opportunities into explicit DEMO trade actions using momentum, sentiment, risk, freshness, liquidity, spread and scenario validation.
---

# Decision Engine

## Purpose
Turn a qualified candidate into an explicit DEMO action or a reasoned rejection.

## Core checks
- freshness of catalyst and price response;
- current momentum;
- liquidity and spread;
- volatility;
- instrument validity in T212;
- whether catalyst is already priced in versus still surprising the market;
- confirmation and invalidation scenario;
- dilution/manipulation risk for penny/low-cap names;
- account exposure and current positions.

## Trade Signal Equation
Use the project signal framework as one input, not as an automatic truth:

S_trade = (w_s * Sentiment + w_m * Momentum) * (1 - sigma / Confidence)

Default working example:
- w_s = 0.6
- w_m = 0.4

Do not use the equation to override broker facts, stale data, liquidity/spread problems or an invalid setup.

## Output
- instrument
- exact T212 ticker
- action: BUY / HOLD / EXIT / NO TRADE
- intended exposure
- entry logic
- target / exit logic
- invalidation / stop logic
- key risks
- evidence
- reason for rejection if NO TRADE

Never call T212 directly.

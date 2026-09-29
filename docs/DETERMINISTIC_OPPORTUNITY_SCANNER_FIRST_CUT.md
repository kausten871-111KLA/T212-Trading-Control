# Deterministic Opportunity Scanner — First-Cut Specification

## Objective
Catch KOD-class early momentum events without waking an LLM every five minutes.

## Runtime principle
Run arithmetic/data checks every 5 minutes.
Invoke DeepSeek only for newly-qualified or newly-escalated shortlist names.

## Initial US-only cut
Use Alpaca + the T212 instrument cache first.
This allows deployment before UK/global market data is added.

## Config
- scan cadence: 5 minutes
- move tiers: 5%, 10%, 20%, 50%, 100%
- relative-volume minimum: 2.0x
- extreme relative-volume: 5.0x
- execution spread ceiling: 2.5%
- watch-only spread ceiling: 5.0%
- minimum price: $0.50
- shortlist: top 20
- max LLM checks per cycle: 5
- max LLM checks per day: 20
- sector cluster flag: 3+
- new-listing window: 30 days
- EOD audit horizon: top 100 movers

## Deterministic gates
1. positive move tier crossed for long-only candidate flow
2. relative volume >= threshold
3. present in T212 instrument master
4. liquidity floor passed
5. spread <= configured ceiling
6. reason/catalyst deferred to DeepSeek

## Deterministic score
Rank on:
- price move
- relative volume
- liquidity
- spread quality

Do not use the LLM for ranking.

## Shortlist state
Persist machine-readable state for each symbol:
- ordinary symbol
- exact T212 ticker
- name
- exchange/currency
- price
- change %
- relative volume
- dollar volume
- spread %
- T212 tradable
- first seen
- latest tier
- rank score
- state

## LLM handoff
DeepSeek is invoked only when:
- symbol is newly qualified, or
- symbol crosses another move tier.

DeepSeek task:
- find/verify catalyst
- return reason tag
- reliable source
- confidence
- qualify/reject for further trading workflow

## EOD missed-green audit
Compare:
- ACTUAL: top market movers
- SURFACED: every scanner shortlist item
- TRADED: broker-confirmed fills

Root-cause codes:
- NEV: never surfaced / detection failure
- RET: surfaced then rejected by deterministic gate
- NOTRADED: qualified but not traded
- TRADED: broker-confirmed fill
- AVOIDED: surfaced but catalyst not verified

Threshold changes are proposed only; never auto-applied.

## Deployment sequence
1. Instrument cache + daily diff
2. US-only deterministic scanner
3. Persist shortlist/ledger
4. DeepSeek catalyst handoff
5. EOD missed-green audit
6. Add UK/global provider later

## Safety
- DEMO only
- no broker writes in scanner
- no LIVE tools
- scanner cannot submit orders
- broker execution remains behind existing T212 DEMO gateway

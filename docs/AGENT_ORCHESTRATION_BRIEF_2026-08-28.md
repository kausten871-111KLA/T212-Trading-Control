# T212 Trading System — Agent Orchestration Brief

**Date:** 28 August 2026  
**Environment:** Trading 212 Demo / practice account

## Current confirmed state
- T212 Demo bridge connected through Cloudflare Worker and GitHub deployment.
- Authenticated read-only account access validated.
- Phase 2 reads cash, positions and combined account state.
- Validated baseline: £300 available, £0 invested, £0 P/L, zero positions.
- Execution remains disabled until the execution-safety gate is completed.

## Objective
Build and test a repeatable evidence-driven trading decision system in Demo before considering controlled live use. The deliberately ambitious experimental benchmark is to test the £300 Demo methodology against the project targets while recording actual performance, failures, drawdowns, false signals and missed opportunities. Targets are experiments, not guaranteed returns.

## Agent workstreams
1. **T212 Engineering & Safety** — maintain Demo/read-only boundary while validating the human approval, risk-limit, broker-side protection and fail-closed execution architecture.
2. **Market Intelligence** — company, sector, macro, geopolitical, event, technical, volume, volatility, liquidity and sentiment intelligence.
3. **Missed-Green Audit** — start with the latest week and extend toward three weeks; identify significant positive movers, what was knowable beforehand, why the system missed them and what detection rule/source should change.
4. **Trader/Source Research** — benchmark evidence-driven penny/day traders, larger-stock day traders and cross-horizon investors. External traders are a signal layer, never a substitute for independent due diligence.
5. **Opportunity Ranking** — combine independent evidence into ranked candidates and produce concise trade decision packets.
6. **Human Control & Reporting** — produce a simple daily proposed-order/position checklist for rapid approval and verification of exits/actions.
7. **Performance & Learning** — measure equity, P/L, hit rate, drawdown, opportunity capture, misses and methodology changes throughout the four-week Demo cycle.

## Daily decision packet
For each qualifying candidate capture: ticker/instrument; catalyst and why-now thesis; corroborating evidence; proposed £ size and entry range; target(s); stop/invalidation and maximum loss; holding period; liquidity/spread/volatility; manipulation/dilution risk where relevant; confidence/uncertainties; human approval status.

## Permanent safety rules
- **FAIL CLOSED:** if ChatGPT/agent availability, credits, required data, API access, Cloudflare, T212 connectivity or system state is unavailable, stale or uncertain, do not open new exposure.
- No open position may depend solely on ChatGPT being available to close it.
- Validate broker-side protective exits/controls in Demo where supported before relying on them.
- Human approval is mandatory before initial Demo execution.
- Define maximum position size, concurrent exposure and drawdown/loss limits before enabling execution.
- Maintain a manual human intervention route through the broker.
- Keep experimental trading funds separate from protected capital and longer-term holdings.
- Periodically protect/remove part of accumulated gains rather than automatically scaling the entire balance into risk.
- A future strategy for profiting from falling prices/short exposure is a separate methodology requiring its own Demo programme and controls.

## Research principle
Price moves must be investigated through observable evidence: announcements, earnings, contracts, approvals, innovation, capital investment, sector sympathy, macroeconomics, geopolitics, policy, commodities, disasters, scientific developments, flows, sentiment, volume and technical behaviour. The key question in every retrospective is not merely what moved, but **what was knowable early enough to act**.

## Human-in-the-loop daily control
The daily sheet should show proposed trades and existing positions with: action, £ size, entry, target, stop/risk, intended hold/exit and approval. End-of-day control confirms planned exits/protection, exceptions requiring manual intervention, infrastructure incidents, thesis invalidation, balance, realised/unrealised P/L and open exposure.

## Four-week Demo cycle
- Week 1: data coverage, missed-opportunity baseline, candidate ranking and human briefing.
- Week 2: refine signal weighting/source quality and proposed-order selection.
- Week 3: reduce noise, concentrate on demonstrated high-value signals and stress-test safety/exception handling.
- Week 4: evaluate repeatability, risk-adjusted results, workload, failure modes and readiness for any next stage.

## Next gate
The Demo account makes order-placement testing financially non-live, but execution should still be introduced in a controlled way so we can test the real workflow safely. Before enabling programmatic Demo execution, complete and validate the human approval mechanism, risk limits, outage/credit fail-safe and exit/protection architecture.

## Standing instruction
Optimise for evidence, opportunity capture, repeatability and capital protection. Actively find qualifying opportunities, but never manufacture a trade to satisfy a quota. Corroborate external trader signals independently. If critical infrastructure or information is unavailable, fail closed and preserve a simple human control path.

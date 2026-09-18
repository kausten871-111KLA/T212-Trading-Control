# Trading Operations Core Method — DeepSeek Knowledge Pack

## Programme purpose
DeepSeek/Open WebUI is the high-volume Trading Operations workhorse. OpenAI remains the project master and sensitive/canonical orchestration layer.

## Operational objective
Build a repeatable DEMO trading system that actually executes, verifies, monitors, exits, audits and learns. Research without broker execution is incomplete.

## Current execution state
- Open WebUI -> DeepSeek Fast: passed.
- Open WebUI -> DeepSeek Batch: passed.
- T212 DEMO gateway: passed.
- T212 DEMO BUY: broker-side fill verified.
- T212 DEMO CLOSE: broker-side closure verified.
- Agent -> T212 tool handshake: passed.
- LIVE: disabled.

## Direct architecture
Programme Owner -> Executive Project Director -> CITO / Trading Orchestrator -> specialist agents -> single T212 DEMO gateway -> broker verification.

## Daily operating logic
1. Scan current greens / movers.
2. Explain cause-effect behind meaningful movement.
3. Qualify momentum, freshness, liquidity, spread, volatility and instrument validity.
4. Compare catalyst surprise versus what appears already priced in.
5. Build confirmation and invalidation scenarios.
6. Produce an explicit DEMO action or a precise rejection reason.
7. Execute valid DEMO actions through the single T212 gateway.
8. Verify every broker write.
9. Monitor and exit.
10. Audit trades and missed greens.
11. Feed learning back into the next cycle.

## Greens / missed-opportunity policy
"Every green is an opportunity to explain" does not mean every green must be bought.
The system must:
- identify major green moves;
- explain why they moved;
- state whether they were tradable;
- state why the system entered or did not enter;
- use misses to improve scanning and timing.

A zero-trade DEMO market day is not automatically a strategy failure if no valid setup exists, but it is an operational exception that must have a precise recorded reason and corrective action if caused by system/process failure.

## Benchmark-trader QC
Use recognised traders as process benchmarks, not copy-trade authorities:
Ross Cameron; SMB Capital / Mike Bellafiore; Steven Dux; Andrew Aziz; TraderTV Live; Humbled Trader; Timothy Sykes; Jack Kellogg.

Compare:
- candidate discovery;
- catalyst recognition;
- entry timing;
- risk framing;
- exit discipline;
- post-trade review.

## Trade Signal framework
S_trade = (w_s * Sentiment + w_m * Momentum) * (1 - sigma / Confidence)

Working example:
- sentiment weight w_s = 0.6
- momentum weight w_m = 0.4

This is a decision aid only. It never overrides:
- stale data;
- poor liquidity;
- unacceptable spread;
- invalid instrument;
- current broker facts;
- explicit risk controls.

## Execution truth standard
Never claim:
- ordered unless T212 accepted the broker request;
- filled unless the position/order state confirms it;
- closed unless broker state confirms closure.

## 20-DEMO-trade recovery
The next validation programme is 20 controlled DEMO trades.
Each trade must record:
- candidate source;
- catalyst;
- entry rationale;
- intended exposure;
- exact T212 ticker;
- quantity;
- broker acceptance;
- fill verification;
- exit rationale;
- closure verification;
- realised result;
- one learning point.

## Reporting style
Default per-trade operational summary:
1. What / why
2. Entry / size
3. Exit / risk
4. Broker status / result

More detail only when needed.

## Current scope
- Buy-side / long DEMO flow first.
- Shorting remains deferred.
- LIVE activation is a separate later phase.

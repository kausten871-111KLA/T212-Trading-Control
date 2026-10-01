# Trading Operations Canonical v3 — PREPARED_NOT_ATTACHED

**Status:** PREPARED_NOT_ATTACHED  
**Environment:** Trading 212 DEMO only  
**LIVE trading:** disabled  
**Purpose:** Durable operating knowledge for DeepSeek/Open WebUI Trading Operations. This pack contains methodology and control rules only. It deliberately excludes historical balances, positions and prices.

## Instruction precedence

1. Current explicit user instruction.
2. Verified broker/environment state and hard safety controls.
3. This canonical trading layer.
4. Current project runbooks and machine-readable control files.
5. Older recovery/implementation documents.
6. General/global model prompt.

Never regress to stale broker facts or older conflicting constraints.

## Operating objective

Run a repeatable DEMO process that moves from fresh market evidence through qualification, decision, controlled approval, broker-verified execution, monitoring, exit, review and learning.

Research is not execution. Configuration is not operation. A successful request is not a fill. A submitted close is not a closed position.

## Core operating functions

### SCOUT
Find broad current opportunities across supported markets:
- positive movers / greens;
- unusual and relative volume;
- momentum and volatility;
- pre-market evidence when supported;
- new-to-market candidates when supported;
- penny-stock and larger/liquid opportunities;
- sector/theme movement.

Produce a timestamped candidate queue. Do not anchor the system to one ticker.

### INVESTIGATOR
For material movers build:
mover -> catalyst -> source verification -> business/financial impact -> price response -> tradability.

Cause confidence:
- CONFIRMED
- PROBABLE
- UNKNOWN

UNKNOWN is valid. Never invent or retroactively rationalise a cause.

### DECISION ENGINE
Apply explicit qualification and deterministic risk gates.

Qualification dimensions include:
- GREEN / RED direction;
- momentum;
- relative volume;
- liquidity;
- spread;
- causal confidence;
- sector/market support;
- early/mid/late move state;
- external corroboration;
- T212 instrument validity.

Use the project signal equation only as a decision aid:

S_trade = (0.6 * Sentiment + 0.4 * Momentum) * (1 - sigma / Confidence)

It never overrides stale data, broker facts, liquidity/spread controls, invalid instruments or risk controls.

### EXECUTOR
The single Trading 212 DEMO gateway owns broker interaction.

Rules:
- exact T212 ticker;
- deterministic sizing;
- explicit approval where required;
- no blind retry of non-idempotent order POSTs;
- broker acknowledgement is not a fill;
- read back after every broker write;
- monitor only broker-confirmed positions;
- exit through the same gateway;
- closure requires broker evidence.

### REVIEWER
Review both executed and missed opportunities:
- entry/exit timing;
- realised DEMO result;
- catalyst validity;
- false positives/negatives;
- detection/qualification latency;
- tool/data/broker failures;
- missed greens;
- one concrete learning item.

## Lifecycle

DISCOVERY -> QUALIFICATION -> CATALYST_VERIFIED -> RISK_GATED -> PROPOSAL -> HUMAN_APPROVAL -> DEMO_EXECUTION -> BROKER_VERIFICATION -> MONITORING -> EXIT -> REVIEW

Rejections and blockers are explicit recorded states. No candidate silently disappears in research.

## Broker truth

Trading 212 DEMO is authoritative for:
- equity and cash;
- positions;
- pending orders;
- fills;
- realised/unrealised results;
- closure state.

Never label model inference as broker-verified.

After process/server restart, perform broker reconciliation before any new DEMO action.

## Shared portfolio authority

UK and US controllers use one broker-mirrored cash/risk/positions pool. They are not separate pots of money.

Pending commitments and candidate reservations reduce available cash. Legacy positions are tracked but do not authorise equivalent new sizing. Prefer consolidated broker reconciliation and avoid bursty API calls.

## Recovered DEMO risk envelope

Recalculate from verified broker equity:
- planned loss/trade: lower of 1% equity or £3;
- position value: lower of 25% equity or £75;
- max concurrent positions: 3;
- aggregate open risk: lower of 3% equity or £9;
- daily loss stop: lower of 2% starting daily equity or £6;
- weekly loss stop: lower of 4% starting weekly equity or £12;
- experiment drawdown stop: lower of 10% high-water equity or £30;
- minimum reward:risk: 2:1 to first target after expected friction;
- normal-session spread ceiling: 2.5% midpoint;
- expected friction: maximum 25% of planned risk;
- proposal validity: 15 minutes;
- reprice/rescale if reference price changes >1%;
- long-only DEMO;
- no shorting, leverage, CFDs, averaging down, martingale or revenge/loss chasing;
- overnight holding disabled by default unless explicitly moved into a separate lane.

Machine-readable source of truth: `webui-control/t212-risk-controls.json`.

## Trading lanes

Intraday: minutes to hours, same-day exit default.  
Swing: 2–10 days, separate rules required.  
Position: weeks to months, separate rules required.

An intraday position must never silently become a swing position because price moved against it.

## Proposal contract

Every proposal must carry:
- timestamp, source and data age;
- candidate source;
- ordinary + exact T212 ticker;
- causal evidence/confidence;
- qualification gates;
- entry range, targets and invalidation/stop;
- liquidity, spread and volatility;
- dilution/manipulation risk;
- intended exposure and quantity;
- broker tradability;
- approval state;
- execution state.

Machine-readable schema: `webui-control/trade-proposal.schema.json`.

## Failure and missed-opportunity taxonomy

Operational codes:
DATA · MARKET · STRATEGY · T212_API · TOOL · AUTH · ORCHESTRATION · EXECUTION · VERIFICATION · HUMAN_ACTION

Missed-opportunity codes:
SCANNER_DETECTION_FAILURE · QUALIFICATION_LATENCY · EXECUTION_INTEGRATION_FAILURE · RULE_THRESHOLD_FALSE_NEGATIVE · FALSE_POSITIVE_QUALIFICATION_FAILURE · EXIT_POLICY_FAILURE · LATE_DETECTION_CHASE_AVOIDED · UNKNOWN_CAUSE · DATA_FAILURE · BROKER_FAILURE

Machine-readable source: `webui-control/t212-failure-taxonomy.json`.

## Zero-trade policy

A zero-trade DEMO day is not automatically a strategy failure. It is an operational exception requiring an explicit reason. If the reason is a system/process failure, record the corrective action. Never invent an opportunity merely to force activity.

## 20-DEMO validation programme

The purpose is process validation, not forced profit. Each controlled DEMO cycle records:
- candidate source;
- catalyst/cause confidence;
- qualification gates;
- ordinary and T212 tickers;
- exposure and quantity;
- broker response;
- fill verification;
- exit reason;
- closure verification;
- realised result;
- rejection/failure code;
- one learning item.

Do not start/continue this programme by bypassing human approval, broker truth or risk controls.

## Benchmark QC

Recognised trading practitioners may be used to benchmark process discipline, not as copy-trade authorities:
Ross Cameron; SMB Capital / Mike Bellafiore; Steven Dux; Andrew Aziz; TraderTV Live; Humbled Trader; Timothy Sykes; Jack Kellogg.

Compare candidate discovery, catalyst recognition, entry timing, risk framing, exit discipline and post-trade review.

## Evidence standard

Never report:
- a current price without a timestamped source;
- an order without T212 acceptance evidence;
- a fill/position without broker read-back evidence;
- a closure without broker closure evidence;
- a component as operational because a prompt/config/file exists.

Durable run evidence and handoffs are required.

## Human intervention

Agents should do everything safely possible themselves. Request human action only for genuinely human-only steps such as secure login/MFA/key entry, permissions, external approvals or material choices.

When blocked report:
BLOCKER · EVIDENCE · IMPACT · KNOWN GOOD · LIKELY ROOT CAUSE · ROUTES · HUMAN INPUT · NEXT TEST

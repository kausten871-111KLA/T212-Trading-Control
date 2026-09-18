# Trading Operations Architecture — 18 Sep 2026

## Objective
Build an execution-first Trading 212 DEMO operations stack in Open WebUI using DeepSeek as the high-volume workhorse while OpenAI remains the master project/orchestration and sensitive-IP layer.

## Current proven baseline
- Open WebUI local browser: operational.
- OpenRouter -> DeepSeek Fast: passed.
- OpenRouter -> DeepSeek Batch: passed end-to-end in browser.
- Server-side OpenRouter credential injection: passed.
- T212 DEMO credentials loaded server-side.
- Open WebUI T212 execution Function installed and callable.
- HELP acceptance test passed.

## Immediate acceptance gate
A broker-confirmed DEMO lifecycle:
1. Resolve Aethlon Medical from T212 instrument metadata.
2. Submit an explicitly approved small DEMO BUY.
3. Capture T212 broker order response / order id.
4. Verify the position in T212.
5. Submit controlled close/sell.
6. Verify closure.

Reading data is not a standalone project gate. Reads are used only as part of execution and verification.

## Important API constraint
Trading 212's Public API currently accepts market orders by QUANTITY only; placing orders by monetary VALUE is not supported through the API. Natural instructions such as "BUY £10 Aethlon Medical" therefore require:
- T212 instrument resolution;
- an external/current market quote;
- FX conversion when instrument currency differs from account currency;
- quantity calculation and rounding;
- then T212 quantity order submission.

This is an implementation requirement, not a blocker.

## Single-gateway rule
All trading agents must use one broker gateway. No agent may call T212 directly.

## Operational groups
### 1. Market Intelligence
- Scanner
- Catalyst/news
- Technical/momentum

### 2. Decision Engine
- qualification/scoring
- risk
- proposed action

### 3. Execution & Position Control
- T212 execution bot
- broker verification
- position monitor
- exits

### 4. Learning & QA
- missed-greens auditor
- trade performance
- cause/effect review
- benchmark-trader comparison

## Loop
SCAN -> EXPLAIN -> QUALIFY -> DECIDE -> EXECUTE -> VERIFY -> MONITOR -> EXIT -> AUDIT -> LEARN

## OpenAI / DeepSeek split
OpenAI retains:
- sensitive GSC360 / commercial information;
- NSTR / RT IP;
- final project master records;
- cross-project orchestration;
- final high-value deliverables.

DeepSeek/Open WebUI handles:
- Trading Operations;
- high-volume market processing;
- You Heal content production using non-sensitive inputs;
- Books & Publishing workhorse tasks using bounded/sanitised briefs;
- Apps / Plugins / Bots build and research.

Do not wholesale-copy OpenAI projects into DeepSeek.

## Initial Open WebUI projects
1. Trading Operations
2. You Heal Content Production
3. Books & Publishing
4. Apps / Plugins / Bots

## Security
- DEMO only until explicit future live activation.
- No credentials in chat, source code, GitHub, or browser-visible configuration.
- T212 keys are server-side environment secrets.
- Duplicate-order protection required because T212 market order POST is non-idempotent.
- LIVE remains disabled.

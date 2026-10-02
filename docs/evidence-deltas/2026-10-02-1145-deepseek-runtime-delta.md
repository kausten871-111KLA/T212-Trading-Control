# DeepSeek AM runtime delta — 2 October 2026

## Source status
Katie supplied a current Trading Operations / DeepSeek WebUI report. Treat broker/account figures and automation changes in that report as WebUI-reported runtime evidence pending relay/export reconciliation. Repository branch evidence is independently inspectable.

## Critical architecture correction
Do not use an LLM chat automation as the five-minute timer. The repository now contains a deterministic systemd discovery timer plus a pre-provider session gate, persistent slot lock and deduplication. Preserve the five-minute deterministic scanner concept, but it must run as a worker/state pipeline and must not open ~92 DeepSeek chats/day. Two bounded supervisory WebUI runs may remain, while candidate/catalyst reasoning is event-driven.

## Repository facts at reconciliation
- Branch had reached c004902 before this delta; Katie autonomy override added at 7ed0b3d5.
- `worker/session_gate.py` provides Europe/London 14:20–21:05 weekday gating, a process lock and persistent per-slot deduplication.
- `worker/produce_market_snapshot.py` plus `openwebui/tools/scanner_metrics.py` already compute a 20-session volume baseline and relative volume when runtime-wired. Therefore RVOL is not a missing algorithm; runtime deployment/wiring is the gap.
- `trading212_demo_gateway_v03_selfcontained.py` implements cache-first instrument lookup and GET backoff, but remains a candidate until runtime-proven.
- `openwebui/trading212_demo_execution.py` v0.3.1 still performs metadata lookup directly and uses only in-process 30-second order deduplication. Gateway consolidation is therefore required.
- Current repository gateway code exposes market order execution only. Official T212 Public API supports DEMO limit, stop and stop-limit endpoints; add them with broker readback and non-idempotent-write protection.
- `webui-control/t212-methodology.json` and `t212-agent-bindings.json` still contain older human-approval/no-broker-write language. The dated autonomy override is the current explicit-user precedence until those canonical files are reconciled.

## Immediate build queue
1. GATEWAY CONSOLIDATION: deploy one cache-first DEMO gateway; remove metadata-per-lookup runtime path; prove cache mount/TTL/429 behavior.
2. CROSS-RUN ORDER SAFETY: add persistent shared order-intent lock/dedup plus broker reconcile-before-write. In-process 30-second fingerprints are insufficient across independent WebUI runs.
3. PROTECTIVE ORDERS: add DEMO limit/stop/stop-limit methods and verify with broker readback. Do not add LIVE endpoints.
4. CATALYST SPEED: first wire Alpaca `GET /v1beta1/news` using existing server-side Alpaca credentials; only add another provider if measured coverage/latency is insufficient.
5. RUNTIME METHODOLOGY: feed computed RVOL, spread/liquidity, catalyst confidence, p_green/S_trade and risk sizing into the actual decision/execution path. Record exact rejection reason for every surfaced candidate.
6. LEARNING: persist the 20-trade validation record and surfaced→qualified→rejected/executed→outcome/missed-green lineage.
7. NEW ON T212: derive automatically from daily instrument-cache diffs. Katie screenshots/pastes are optional for exact in-app-panel comparison, not an operating dependency.
8. RUNTIME ROLE PROOF: prove Market Intelligence, Decision, Execution/Position Control and Learning/QA bindings in WebUI; prompts/skills alone are not persistent agents.
9. CREDIT CONTROL: deterministic workers for scan/freshness/dedup; model calls only for candidate reasoning and bounded supervision; report model-call count/credit use.

## Today acceptance
DEMO execution is authorised without per-trade human approval; LIVE remains disabled/inaccessible. A successful day must show broker-evidenced DEMO lifecycle records and methodology evidence, not merely scheduled chat runs. If no trade occurs, classify the exact upstream failure and repair it; do not call approval/read-only state the blocker.

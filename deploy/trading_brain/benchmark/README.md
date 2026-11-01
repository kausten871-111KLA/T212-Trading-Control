# Sprint 2 — Frozen 20-stock Trading Brain benchmark

**Status:** Frozen dataset and automated comparison harness tested; real model decision comparison **not yet executed**.

**Input:** User-supplied DeepSeek/Alpaca EOD snapshot with 20 symbols, stated observation timestamp 2026-10-20 21:40 UTC. Raw vendor response receipts were not independently retrieved here. Dataset is NOT live price data and has no confirmed broker executable quotes.

**Fairness:** Keep the 20 original symbols and numeric fields intact. Existing DeepSeek `WATCH`/`REJECT` judgements are retained in the original fixture as historical context but are **removed from both models' shared evidence** to avoid anchoring the challenger. Catalyst descriptions are hypotheses, not verified press releases. Every symbol lacks VWAP, RVOL, exchange and quote timestamp. No forced exclusion is applied to a penny stock or leveraged ticker.

**Reproduction on Contabo** — source worktree `/home/katie/t212-brain-benchmark-stage-20261020/deploy/trading_brain/benchmark`; isolated Docker image `local/tradingagents-brain:0.7.0-e8f5503`:

Run the unit tests with no network and no model/broker access:

    docker run --rm --network none --read-only --tmpfs /tmp:rw,size=64m --security-opt no-new-privileges -e HOME=/tmp -v /home/katie/t212-brain-benchmark-stage-20261020/deploy/trading_brain/benchmark:/workspace:ro -w /workspace local/tradingagents-brain:0.7.0-e8f5503 python -m pytest test_trading_brain_benchmark.py -q -p no:cacheprovider

Result 20 Oct 2026: **6 passed**.

Actual upstream TradingAgents bull/bear/trader function wiring (all 20 rows, **60 deterministic MOCK calls**, no model inference, no orders):

    docker run --rm --network none --read-only --tmpfs /tmp:rw,size=64m --security-opt no-new-privileges -e HOME=/tmp -v /home/katie/t212-brain-benchmark-stage-20261020/deploy/trading_brain/benchmark:/workspace:ro -w /workspace local/tradingagents-brain:0.7.0-e8f5503 python native_tradingagents_role_smoke.py

Result: `NATIVE_TRADINGAGENTS_ROLES_SMOKE_PASS symbols 20 mock_llm_calls 60 real_model_calls 0 broker_orders 0`.

**Prepared research prompts:** `prompts/trading_brain_baseline_20.md` and `prompts/trading_brain_debate_20.md`. Both include identical JSON evidence with SHA256 `cbf27160ec376c2355729d1f1eeb05e6a30082128eff2c46b99fa617f32c49d1`. The first asks DeepSeek to use its existing strategy; the second asks for TradingAgents-*style* bull/bear/trader deliberation. **Running the second prompt in DeepSeek alone is not equivalent to running the upstream TradingAgents graph.** A genuine TradingAgents run needs the installed native nodes and an authenticated model call.

**Next step:** Obtain baseline DeepSeek JSON from the first prompt. Then conduct one budgeted native TradingAgents bull/bear/trader evaluation using the same frozen EOD data. Store model responses separately, validate schema, and compare only research decisions/justifications initially. Do not claim improved profit, filled orders, or statistical advantage without subsequent independent quotes and broker receipts. No permanent changes to DEMO strategy, schedules, LIVE flag or gatekeeper functions in this sprint.

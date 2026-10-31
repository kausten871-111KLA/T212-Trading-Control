# Trading Brain / FinMem — source-backed bootstrap (22 October 2026)

## Verified production state
The existing registered `trading_brain_research_context` tool in Open WebUI has SHA-256 `c003a2ae8fb2c4c77b9cf9e0ac345222db90cb5cb1a71cdbba432dcfca9a1ba6`. It is **an exact fingerprint match** for the GitHub Twelve Data-enabled staged source `deploy/trading_brain/components/trading_brain_webui_bundle_twelve_stage.py`. Therefore Twelve Data → Trading Brain normalization was **already deployed**; no replacement or duplicate tool registration was needed. The user-provided DeepSeek report says both `trading_brain_research` and `twelve_data_research` were successfully called from the controlling session, so the previous tool-visibility blocker is closed.

## Journal bootstrap
The production memory tool already opens its optional journal at:

`/app/backend/data/trading_brain_research/finmem.sqlite3`

This previously did not exist. On 22 October 2026, a new **independent research-only** SQLite journal was created and installed there. It contains **3 authentic historical TradingAgents v0.7.0 recommendations**: BRZE proposed HOLD, MYGN proposed BUY, PRSO proposed HOLD. The original research occurred `2026-10-20T22:39:03.982676+00:00` via real DeepSeek/OpenRouter calls. Evidence SHA-256 `cbf27160ec376c2355729d1f1eeb05e6a30082128eff2c46b99fa617f32c49d1` was recomputed from the original frozen source and verified before import.

**The DB contains 3 research decisions, 0 outcomes, 0 reflections and 0 broker executions.** These recommendations are NOT broker fills, trade instructions or claims of profit. A separate user-supplied DeepSeek baseline of 20 decisions was not imported because its `assessed_at_utc` is null: inventing an assessment timestamp would violate point-in-time chronology.

Source/bootstrap:
- `deploy/trading_brain/components/seed_finmem_from_research.py` — source-checked, idempotent import with exact record comparison; preserves any actual existing outcomes/reflections if rerun, never overwrites altered decisions.
- `deploy/trading_brain/components/test_finmem_seed.py` — 10 provenance/replay/anti-hindsight tests.
- Existing `finmem_research.py` — schema, read-as-of, tiered memory, separate dated outcomes/reflections.

Production DB was created with container-owned restricted directory mode 0700 and file mode 0600; initial copy was also backed up on Contabo:

`/home/katie/backups/finmem-bootstrap-20261022/finmem-bootstrap.sqlite3`

This journal is independent of the production controller `~/.local/state/deepseek-runtime/trading_state.db`.

## Critical limitation: actual trading performance
The controller's own `decision`, `intent`, `order`, `position`, `pnl_record` and `trade_review` tables were each empty at the time of this sprint. The user-provided DeepSeek report says direct Trading 212 `list_positions` and `recent_order_history` showed broker-confirmed fills/SELLs. Those may exist in Open WebUI automation tool receipts or the real brokerage, but are not yet stored in this controller database. **Do NOT claim learning from actual P&L or fills.**

To build outcome learning next, obtain actual broker receipt details with stable order IDs, side, quantity, filled price/time, symbol/currency and reconciliation to the prior research decision. Record outcomes only after independent broker verification. Never convert proposed BUY/HOLD into a FILLED trade. Add future decisions to the journal using a verified, authenticated and append-only research ingress, without letting a research tool place orders or read broker credentials.

## Tests and deployment checks
The 10 seed tests pass; initial seed yielded `created=3`, and a repeat yielded `created=0` (idempotence). Production journal `PRAGMA integrity_check=ok`, research decisions 3, outcomes 0, reflections 0, symbols BRZE/MYGN/PRSO.

All existing four automations must remain active and unchanged, and LIVE disabled.

## Controlled post-install acceptance request to DeepSeek
After refreshing the Trading Operations chat, use existing Alpaca snapshot for MYGN and call `trading_brain_research(ticker="MYGN", ...)` with a current as-of UTC timestamp. Confirm `history_as_of` includes the authentic original 20 October TradingAgents MYGN research BUY *recommendation*, clearly labeled `NOT AN ORDER` and `NOT AN OUTCOME`. It must contain no broker fill or P&L claim. The model may independently reject or revise that old recommendation using fresh market data; FinMem should supply history only.

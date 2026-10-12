# Legacy T212 DEMO gateway — metadata cache and read pacing repair

**STAGED, NOT DEPLOYED.** Independent P1 patch of the exact installed v0.2.0 source SHA256 4acf6583dd6b41630282de972b5ed20a47705bce477dc2c3a1bd13311712adbe from branch feature/t212-instrument-cache-v03 base cc276536a0b6a53599b1b287fa0bce7b449f9dcb. This fix does not depend on the unfinished PR8/9/10 BUY pathway.

## Implemented

- Version 0.2.1-cache-candidate; all 10 public Tool methods preserved. AST comparisons show place_market_order, close_position, list_positions, list_orders, _credentials and size_quantity unchanged versus source baseline. No changes to risk policy, order mutation logic, credentials or automations.
- find_instrument uses a private persistent SQLite catalogue inside existing mounted WebUI data directory (default /app/backend/data/t212-legacy-metadata.sqlite3), 600-second TTL, persisted 55-second minimum refresh interval, cross-worker reservation, 45-second lease and no blind retry. Stale metadata is explicitly STALE_RESEARCH_ONLY, not order/execution verification.
- Account-summary GET, positions GET and pending orders GET are paced at 5.5s, 1.25s and 5.5s through distinct persisted account/route budgets; account/position/order states are **NEVER cached**. Busy responses indicate a delay rather than returning stale account state. HTTP 429 Retry-After or x-ratelimit-reset headers can extend read cooldown.
- T212_DEMO_ACCOUNT_SCOPE is an optional **NON-SECRET** stable account identifier to share throttle budgeting when multiple DEMO API keys use the same account. Without it, the fallback hashes the current API key plus DEMO base URL, which cannot eliminate account-wide 429s from unrelated clients or keys.

## Reproduction

Run from isolated checkout root with **network disabled**:

    docker run --rm -i --network none --read-only --tmpfs /tmp:rw,nosuid,nodev,mode=1777 -e WEBUI_SECRET_KEY=synthetic-test-only -e PYTHONPATH=/app/backend:/work -v /tmp/t212-legacy-demo-cache-20261012:/work:ro -w /work --entrypoint python ghcr.io/open-webui/open-webui:v0.11.4 -m unittest discover -s tests -p 'test_legacy_metadata_cache.py' -v

14 PASS. Fixtures include four concurrent child processes issuing one synthetic catalogue GET; persisted fresh lookup; synthetic actual HTTP 429 header, cooldown and no automatic retry; scoped state; broker GET pacing; stale warning; damaged cache fail-closed; unchanged legacy MARKET BUY/SELL request semantics. No real API or trade was performed.

Official T212 published limits used: metadata 1/50s, summary 1/5s, positions 1/1s, pending orders 1/5s. Rate limits are per broker account (not per key). See https://docs.trading212.com/api.

## P0 decision and safe deployment

Read-only installed WebUI DB on 12 October: trading-operations--deepseek continues to attach the 10-method legacy T212 DEMO gateway and market_data_gateway. Three OPEN/MIDDAY/CLOSE automation prompts explicitly identify as READ-ONLY **helpers**, and assign order submission to the controlling DeepSeek chat. Do not infer from these helper prompts that the controller itself is technically unable to place a MARKET order; nor rewrite the schedules into competing order owners. Ask DeepSeek to confirm whether its controlling chat's temporary BUY restriction was an engineering coordination instruction rather than an execution-tool failure.

PR10's BUY containment is limited to the **uninstalled candidate** and does not supersede previously approved legacy DEMO controller authority. Continue to enforce original cash/exposure/loss, instrument/quote, spread/liquidity, protective-exit and reconciliation conditions, and DEMO-only/LIVE-disabled restrictions. Legacy MARKET POSTs are non-idempotent and have only a process-local 30s duplicate guard; this patch does not solve restart safety or install STOP methods.

Engineering only: obtain exclusive production writer lease; verify installed source SHA and grants; take private backup; validate persistence permissions and current account scope; perform guarded WebUI tool replacement and reversible rollback; coordinate with DeepSeek for read-only smoke tests and natural authorised trading afterwards. User's directive does **not** itself authorise production changes or forced orders.

## Remaining limits

Not a deployed 429 resolution. Unrelated keys/apps and history endpoints may still hit 429. SQLite assumes one shared local host/volume. Busy GETs may defer broker-state availability, which must never be mistaken for safe permission to trade using stale data. PR8/9/10/11/12 remain separate work.

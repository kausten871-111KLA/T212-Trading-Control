# T212 Gateway v0.3 Controlled Installation / Rollback

Do not replace the live Open WebUI tool until the self-contained candidate passes the container read-only test.

## Pre-install
1. Export the current `trading_212_demo_gateway_tool` source.
2. Create a SQLite online backup of `/app/backend/data/webui.db`.
3. Confirm T212 DEMO credentials are present and LIVE remains disabled.
4. Run `scripts/test_gateway_v03_readonly.py` against the candidate.
5. Confirm output contains `ORDERS_SUBMITTED=0`.

## Install
Use Open WebUI Site Configurator only after backup. Replace only the T212 DEMO gateway tool source. Do not alter market-data tool, automations, model bindings, or schedules in the same change.

## Smoke test
Read-only calls first:
- instrument_cache_status
- find_instrument("Apple")
- new_on_t212
- trading_dashboard
- list_positions
- list_orders

Then verify:
- environment = DEMO
- liveTradingEnabled = false
- account/positions/orders still reconcile
- repeated find_instrument uses cache

## Rollback
If any smoke test fails:
1. Restore the exported v0.2 tool source.
2. Do not retry broker POST actions.
3. If configuration state is damaged, restore the SQLite online backup.
4. Re-run read-only dashboard reconciliation.

# T212 Gateway v0.3 Controlled Installation / Rollback

Do not replace the live Open WebUI tool until the self-contained candidate passes the container DEMO-only test.

## Pre-install
1. Export the current `trading_212_demo_gateway_tool` source.
2. Create a SQLite online backup of `/app/backend/data/webui.db`.
3. Confirm T212 DEMO credentials are present and LIVE remains disabled.
4. Run `scripts/test_gateway_v03_readonly.py` against the candidate.
5. Confirm output contains `ORDERS_SUBMITTED=0`.

## Install
Use Open WebUI Site Configurator only after backup. Replace only the T212 DEMO gateway tool source. Do not alter market-data tool, automations, model bindings, or schedules in the same change.

## Smoke test
DEMO-only calls first:
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
4. Re-run DEMO-only dashboard reconciliation.


## Shared-cache deployment contract

The host worker and the Open WebUI gateway must use the same underlying directory:

- host: `/var/lib/t212-scanner`
- container: `/app/backend/data/t212-scanner`
- cache: `t212_instrument_cache.json`
- diff: `t212_instrument_diff.json`
- refresh lock: `t212_instrument_cache.lock`

Required container environment:

```text
T212_INSTRUMENT_CACHE_PATH=/app/backend/data/t212-scanner/t212_instrument_cache.json
T212_INSTRUMENT_DIFF_PATH=/app/backend/data/t212-scanner/t212_instrument_diff.json
T212_INSTRUMENT_CACHE_TTL_SECONDS=86400
```

The host directory must be bind-mounted read/write at the container directory above. Do not guess or recreate the container until its existing compose/run configuration and rollback anchor are identified.

Read-only mount inspection:

```bash
docker inspect open-webui --format '{{range .Mounts}}{{println .Source "->" .Destination}}{{end}}'
```

Success requires an exact `/var/lib/t212-scanner -> /app/backend/data/t212-scanner` mapping. If absent, status is **BLOCKED_NOT_SHARED**; do not install the gateway candidate yet.

## Candidate acceptance

From the exact reviewed checkout, before replacing the live tool:

```bash
python -m unittest -v tests.test_gateway_cache_acceptance tests.test_cache_worker_acceptance
python scripts/test_gateway_v03_readonly.py openwebui/tools/trading212_demo_gateway_v03_selfcontained.py
```

The live read-only test must report:

- `GATEWAY_V03_DEMO_TEST=PASS`
- `TEN_LOOKUPS_METADATA_REDOWNLOADS=0`
- `LIVE_TRADING_ENABLED=False`
- `ORDERS_SUBMITTED=0`

A stale cache may be used only as an explicitly labelled `stale-disk-fallback`; freshness-dependent discovery must continue to fail closed.

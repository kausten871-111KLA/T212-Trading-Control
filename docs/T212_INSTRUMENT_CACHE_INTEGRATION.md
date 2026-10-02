# T212 Instrument Cache Integration — v0.1

## Purpose
Reduce repeated calls to Trading 212 instrument metadata, prevent avoidable 429s, and create a deterministic "New on T212" daily diff.

## Current implementation
Branch: `feature/t212-instrument-cache-v03`

New helper:
`openwebui/tools/t212_instrument_cache.py`

This helper is read-only. It never places, modifies, or cancels orders.

## Intended runtime paths
- Cache: `/app/backend/data/t212_instrument_cache.json`
- Diff: `/app/backend/data/t212_instrument_diff.json`

These sit inside Open WebUI's persistent data volume.

## Integration into Trading 212 DEMO Gateway

### 1. Instantiate once
Import `InstrumentCache` and create:
`self.instrument_cache = InstrumentCache()`

### 2. Replace per-search full metadata download
Current `find_instrument()` calls:
`GET /equity/metadata/instruments`

Change the flow to:
1. load cache
2. if fresh (<24h), search locally
3. if missing/stale, fetch instrument master once
4. save snapshot + diff
5. search local cache

### 3. Add read-only tool methods
Recommended:
- `refresh_instrument_cache(force: bool = False)`
- `instrument_cache_status()`
- `new_on_t212(limit: int = 100)`

### 4. Daily refresh
Use one server-side schedule after deployment.
Recommended refresh: once daily before first market-discovery run.

Do not use an LLM to maintain the cache. This should be deterministic server-side work.

## First-run behaviour
The first snapshot creates the baseline.
Do not label all first-run instruments as "new".

Only the second and subsequent snapshots can produce a meaningful newly-added list.

## Daily diff output
Track:
- added tickers
- removed tickers
- changed metadata

Tracked metadata:
- name
- shortName
- ISIN
- currency
- type
- extended-hours status
- max open quantity

## Acceptance test
1. Cache absent.
2. Refresh once -> one T212 metadata call.
3. Confirm cache file written.
4. Run ten `find_instrument` lookups.
5. Confirm no additional metadata calls while cache is fresh.
6. Force a second refresh.
7. Confirm diff file is generated.
8. Confirm all trading remains DEMO and LIVE remains disabled.

## Safety
- Read-only broker endpoint only.
- No keys are written to cache files.
- No execution behaviour changes until gateway integration is separately reviewed.
- Do not merge/deploy without checking current installed WebUI tool source against repo source.


## Canonical shared path and lock

The gateway and host refresh worker now coordinate through one underlying bind-mounted directory.

| Runtime | Directory |
|---|---|
| Host worker | `/var/lib/t212-scanner` |
| Open WebUI container | `/app/backend/data/t212-scanner` |

Both sides use the same filenames and the same `t212_instrument_cache.lock`. The gateway re-reads the cache after acquiring its in-process and file locks, preventing concurrent refreshes from redownloading the metadata master.

The gateway performs deterministic bounded GET retries: 1s, 2s and 4s unless a valid broker `Retry-After` header is supplied (clamped to 0.5–15s). Broker POST requests are never retried.

If refresh still fails and a prior cache exists, the gateway/worker preserve it and label the source `stale-disk-fallback`. They do not silently mark stale data fresh. Downstream freshness gates remain authoritative.

## Branch-side acceptance evidence

The offline acceptance suite proves:

1. ten sequential fresh-cache lookups make one metadata fetch total;
2. ten concurrent lookups share one refresh;
3. no POST/order path is called;
4. cached data survives a provider 429;
5. retry timing is deterministic and bounded;
6. cache files are private (`0600`).

This is source-code evidence only. Runtime mount, credentials, live tool source and container behavior remain unverified until the controlled installation runbook passes.

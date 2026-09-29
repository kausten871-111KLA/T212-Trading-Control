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

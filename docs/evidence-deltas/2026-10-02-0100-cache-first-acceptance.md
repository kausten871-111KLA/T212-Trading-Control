# Evidence delta — T01–T04 / T07 / A07 cache-first acceptance

**Recorded:** 2 October 2026  
**Tested code commit:** `a6d228b7213b8f8d5d01f0b8b3bde11be75044bf`  
**GitHub Actions:** WebUI Control Plane CI run 74 — SUCCESS  
**State:** STAGED_NOT_DEPLOYED  
**Live effect:** none

## Register deltas

| Item | New evidence | Status |
|---|---|---|
| T01 | The self-contained v0.3 candidate reads the instrument master through a persistent cache and reports its resolved cache path. | STAGED |
| T02 | Offline acceptance proves ten sequential fresh-cache lookups cause one metadata fetch total; the live read-only script now asserts zero redownloads across ten lookups. | STAGED; container proof pending |
| T03 | GET-only 429/5xx retry timing is deterministic and bounded at 1s, 2s and 4s, or a valid broker Retry-After clamped to 0.5–15s. POST requests remain single-attempt. | STAGED |
| T04 | An existing cache survives a provider 429 and is explicitly labelled `stale-disk-fallback`; freshness-dependent discovery remains fail-closed. | STAGED |
| T07 | Controlled installation/rollback documentation now requires the exact shared bind mount and retains source/database backup and DEMO-only smoke gates. | STAGED |
| A07 | Gateway and host worker now coordinate through one underlying cache directory and one `t212_instrument_cache.lock`; same-process concurrent lookups also share one refresh. | STAGED; runtime mount pending |

## Shared-cache contract

- host worker: `/var/lib/t212-scanner`
- Open WebUI container: `/app/backend/data/t212-scanner`
- required bind: `/var/lib/t212-scanner -> /app/backend/data/t212-scanner`
- cache, diff and lock files are written privately; cache and lock acceptance confirms mode `0600`.

No container recreation or mount change was attempted because runtime access and the current container launch/compose definition are not available.

## Verification

- isolated cache acceptance: **7 passed**
- ten sequential lookups / one metadata fetch: **PASS**
- ten concurrent lookups / one refresh: **PASS**
- zero POST/order calls: **PASS**
- stale-cache preservation after 429: **PASS**
- deterministic bounded retry: **PASS**
- source compilation: **PASS**
- complete GitHub unit suite: **PASS**
- control-plane preflight: **PASS**
- logical workspace contract: **PASS**
- workspace isolation audit: **PASS**
- implementation and T212 gap-register builds: **PASS**
- tracked dotenv/secret check: **PASS**
- safety evidence: DEMO only; LIVE disabled in candidate; `orders_submitted=0`.

## Source versus live truth

This proves the branch implementation only. It does **not** prove:

- the live Open WebUI tool has moved from the reported v0.2 source to v0.3;
- the shared container bind mount exists;
- the host worker is installed or enabled;
- the live DEMO credentials are available to the candidate;
- the provider accepted a fresh runtime metadata refresh.

The controlled installation must stop at **BLOCKED_NOT_SHARED** if the exact bind mount is absent. No broker POST should be used to demonstrate the cache.

## Exact next item

Proceed to **T05–T11 / D01–D07** discovery-pipeline acceptance:

1. trace fresh snapshot producer through scanner, cache mapping, relative-volume/fallback and spread gates;
2. prove the structured catalyst queue has an actual consumer;
3. add closed-market fixtures labelled as fixtures, never fresh market evidence;
4. generate a Friday pre-open no-order go/no-go artifact;
5. keep all runtime-dependent findings explicitly STAGED or BLOCKED.

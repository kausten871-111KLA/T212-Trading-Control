# Evidence delta — T12 / A06 / S08 session control

**Recorded:** 2 October 2026  
**Tested code commit:** `42def30e62a5b60e5417d6782fe6d921531b0a8c`  
**State:** STAGED_NOT_DEPLOYED  
**Live effect:** none

## Register deltas

| Item | Previous evidence | New evidence | Status |
|---|---|---|---|
| T12 | One live WebUI automation was reported active, but its 5-minute RRULE was not independently proven to contain a deterministic market-hours gate. | Branch-side discovery now has an explicit `Europe/London` session gate before snapshot/cache/scanner/provider work. It allows weekday slots from 14:20 through the 21:05 slot only. | STAGED; live WebUI automation remains externally unverified |
| A06 | Persistent discovery worker staged; source timer fired every five minutes all day. | Systemd timer is restricted to the same weekday 14:20–21:05 UK outer boundary. An internal gate independently enforces the window. | STAGED; not installed/enabled at runtime |
| S08 | Cost control designed, but overnight provider/model calls were still possible if scheduling drifted. | Out-of-window worker invocations return before any snapshot, cache, scanner, model or provider work. | STAGED |

## Reliability controls added

- Non-blocking process lock rejects overlap.
- Persistent five-minute slot state rejects duplicate completed runs.
- A failed slot receives at most one bounded retry.
- A stale RUNNING marker is recoverable after the four-minute service timeout.
- Weekend, start/end boundary, bounded misfire and UK daylight-saving behavior are deterministic.
- Worker remains read-only and records `orders_submitted=0`.
- The register's 14:20–21:05 boundary is preserved as an outer safety boundary; this change does not redefine the canonical UK_OPEN/US_OPEN/US_CLOSE methodology windows.

## Verification

- Fresh-checkout repository preflight: **PASS**
- Unit tests: **107 passed**
- Configurations: **21 validated**
- Components: **34 validated**
- `systemd-analyze verify`: **PASS**
- Summer and winter timezone boundary tests: **PASS**
- Weekend and 21:05 bounded-misfire tests: **PASS**
- Overlap, duplicate-slot and bounded-retry tests: **PASS**
- Out-of-window no-discovery ordering test: **PASS**
- T212 safety: DEMO; LIVE disabled; order mutation disabled

## Source versus live truth

This evidence proves the branch implementation only. It does **not** prove:

- the live WebUI automation prompt or scheduler has equivalent deterministic gating;
- the runtime at `/home/katie/t212-scanner` contains this commit;
- the systemd unit is installed or enabled;
- the relay is active; Issue #5 still has no `[WEBUI→CHATGPT]` acknowledgement.

## Exact next item

Proceed to **T01–T04 / T07 / A07** branch-side cache-first acceptance:

1. validate shared cache path and ownership across container/worker;
2. add deterministic 429 backoff and stale-cache behavior where absent;
3. prove ten fresh-cache lookups cause no metadata redownload;
4. prove scanner output remains `orders_submitted=0`;
5. prepare exact install/rollback commands without claiming deployment.

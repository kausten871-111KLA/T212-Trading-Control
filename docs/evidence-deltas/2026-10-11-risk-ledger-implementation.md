# 11 October 2026 implementation sprint receipt

STAGED, NOT DEPLOYED. Production release remains NO-GO.
Baseline PR8 bf6ec10274652edf412bde355ea4e58791010a8a; stacked on PR9 7fea6c450e9bdd43f4aff214907b992f5d4bbbd5. Isolated branch: fix/risk-containment-ledger-20261011. Existing shared Engineering branches untouched.

## Delivered code
- Actual Tool/Pipe mutation boundary rejects every new BUY before transport. Malformed private mutations fail closed. This is interim containment: it blocks valid BUYs too, and is NOT completed risk admission.
- Standalone evaluator rejects future timestamps, missing/nonfinite/negative portfolio metrics, understated exposure, forbidden strategy flags, and uses conservative entry-high loss sizing. Approved DEMO position-count relaxation retained.
- Pure request binder ties intent/account/exact execution payload/quantity/GBP conversion/fresh verified FX to evaluator PASS. NOT connected to gateway; caller booleans are not authenticated provenance.
- Opportunity ledger has event/correlation IDs, Linux cross-process append locking, fsync, mode0600, symlink refusal and strict JSON. Scanner IDs persist through actual queue and mocked reviewer output.
- Runbook moves safety gates before apply; previous port3000 receipt needs current host readback.
- Exact PR7 claim_due source fixture demonstrates committed next_run_at before task creation can lose an occurrence. No PR7 fix claimed.

## Exact acceptance commands and observed results
```sh
python3 -m unittest discover -s tests -p 'test_risk*.py' -v
# 25 methods PASS
python3 -m unittest discover -s tests -p 'test_opportunity_ledger_durability.py' -v
# 5 methods PASS; 4 OS processes, 100 unique parseable events; immediate process-exit persistence
python3 -m unittest discover -s tests -p 'test_scan_event_correlation.py' -v
# 1 method PASS; actual ledger/queue/consumer, mocked scanner/tier/reviewer
python3 -m unittest discover -s tools/acceptance -p 'test_claim_crash_window.py' -v
# 1 reproduction PASS: committed claim, zero tasks, occurrence no longer due; defect remains
```
Test execution occurred in isolated scratch staging on 11 October; paths above apply after checkout. Risk gateway import uses fail-fast httpx import stub when unavailable; all transports mocked, no broker/provider calls. Baseline direct BUY fixture reproduced one mock POST; corrected candidate zero. Old evaluator reproduced22 negative assertion failures before fixes. These are offline evidence, not real router/runtime/broker acceptance. No rerun or claim of the old195 suite. Historical valid BUY fixtures require intentional rebaselining because the admission contract changed; old exposure50 vs quantity5*entry_high10.1 must become50.5.

Additional changed-source regression:
```sh
python3 -m unittest discover -s tests -p 'test_catalyst_queue_concurrency.py' -v
# 4 PASS: 4 processes retain81 unique events, duplicate suppressed; only1 claim wins; private mode/symlink/invalid JSON guards
python3 -m unittest discover -s tests -p 'test_catalyst_consumer.py' -v
# 7 unchanged existing consumer tests PASS
```
Review-log append now locks/fsyncs and refuses symlinks/nonfinite JSON. Two additional tests preserve80 unique reviews across4 processes exiting immediately; existing consumer regression remains7 PASS.

Total44 passing targeted/regression methods, plus1 separate known-defect reproduction. First consumer invocation from parent lacked module search path; rerun from checkout root passed. Queue replacement is fsynced, but no physical power-cut experiment or network-filesystem support claimed.

## Remaining release blockers
1. Trusted broker-account portfolio and FX producer with authenticated provenance and point-in-time loss/risk metrics; no model-supplied PASS.
2. Atomic account-wide risk reservations under the durable journal lock before admitting BUY; evaluate exact payload, preserve exit behavior, handle UNKNOWN without resubmission.
3. Integrate PR9 rollback guards and exercise real disposable WebUI router, permissions, response loss and concurrency. GET→POST checks are not atomic CAS; lease string is not authentication.
4. Shared host/container cache and journal mount, key/account namespace policy, provider/rate/cache acceptance and controlled installation remain unverified.
5. PR7 durable transactional occurrence/outbox recovery plus real-handler two-run/reload/idempotency acceptance.
6. Queue now locks complete local-process mutation transactions, fsyncs replacement and directory; expired-lease owner fencing remains missing. Full scan→intent→broker→exit→outcome mapping remain unfinished. Event IDs do not themselves provide deduplication or power-loss directory durability.

## Owner and next three actions
Engineering sole production executor:
1. Review this isolated candidate and integrate tested containment/evaluator/binder prerequisites with PR9; then implement trusted producer and atomic reservations (effort unknown until producer access contract is confirmed).
2. Complete negative and valid-entry mocked admission matrix plus actual disposable router rollback acceptance; retain exact command/stdout/source hashes (roughly1–3 active hours for fixtures after prerequisites; not an ETA).
3. Continue storage/cache acceptance, while PR7 owner repairs outbox crash window separately; no dependency on deploying this containment-only gateway.
No Katie-only action established. No deployment, broker mutation, paid call or schedule change performed.

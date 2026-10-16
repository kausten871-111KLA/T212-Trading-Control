# Monitor integration delivery — 16 October 2026

## Problem → correction

Night Sprints reported tested but unpublished monitor/worker fixes. PR #17 still
contained the original monitor source at bdda29f3f34b5fa187aa4065f2786521061b151f.
The named Night Sprint 9/10 ZIP packages were not available through current file
retrieval. This delivery independently reproduces the concrete monitor defects;
it does not claim to recover or verify that chat's complete 62-test package.

1. Malformed nested instruments/unhashable tickers crashed a monitor cycle.
   Duplicate or conflicting ticker rows could silently select the wrong quantity.
   The monitor now indexes exact identities, leaves ambiguous watches ACTIVE with
   an explicit reason, and continues unrelated valid watches.
2. The monitor expected a list while the installed-family gateway returns JSON
   text. `DemoMonitorGateway` now decodes positions and calls only the existing
   durable market-intent and reconciliation methods on an injected gateway.
   It checks DEMO endpoint identity on each operation and receipt intent/account
   identity. It creates no HTTP client, credentials, strategy, or schedule.
3. EXPIRED receipts remained UNKNOWN although the gateway journal treats them as
   terminal. The monitor now finalizes EXPIRED and keeps partial fills acknowledged
   for reconciliation. It does not infer a fill from submission alone.
4. GitHub CI did not install httpx. The first run failed with missing imports and
   misleading downstream stub failures. `requirements-ci.txt` and a dependency
   installation step repair the environment, keeping all existing checks.

## Verification

- Identity baseline: 12 tests, 8 failures + 2 errors + 2 passes against original
  source. Corrected tests all pass; original 10 monitor tests also pass.
- Status baseline: 3 new lifecycle tests failed before the status correction.
- Focused final command from repository root:
  `python -m unittest discover -s tests -p 'test_position*.py' -v`
- Gateway integration exercises the actual v0.2.3 source and SQLite intent journal
  with synthetic transport, temporary stores, fake credentials and blocked socket
  connection attempts. Two tests retain the actual `_request`/pacing path and
  replace only HTTP I/O: a normal exit succeeds; 429 persists cooldown without
  burning the ACTIVE watch. No broker calls or paid model calls were made.
- Restart tests show pending → filled, pending → expired and UNKNOWN without a
  second mocked POST. Correct quantity/sign and stable intent reach the journal.
- Commit b20b054b87a2b63f8d7a6a7a93d4dcd39241cfc5 publishes the identity fix.
- Commit 085b976cc2d6aab8476efb7cfafebd28a08170a0 publishes the adapter and CI repair.
  GitHub run 38938873815 passed all steps: 221 unit tests (the existing preflight
  repeats the same suite; do not double-count it as 442 distinct tests).
- Full commands and final local stdout accompany this evidence file. Local
  combined coverage includes 25 existing cache/read-recovery tests to verify the
  CI dependency repair, not a rerun of the unrelated historical 195-test suite.

## Deployment truth and remaining blockers

SOURCE + OFFLINE INTEGRATION only. This sprint does not deploy a worker or modify
the installed gateway, models, settings, automations, or broker account. Existing
PR #17 remains the integration lane; production ownership stays with Engineering.
Cloudflare preview deployment of the repository is not a Contabo monitor rollout.

Host integration is deliberately explicit:

```python
from openwebui.tools.position_monitor_gateway import DemoMonitorGateway

# Existing authenticated host supplies its configured DEMO Tools instance and
# the shared monitor ledger. Do not create a parallel broker writer or journal.
adapter = DemoMonitorGateway(existing_gateway)
result = await adapter.tick(existing_monitor_ledger)
```

The host must enforce controller identity on registration/cancellation and use
the same durable gateway storage/account context as DeepSeek. This module is not
a public HTTP endpoint and does not provide the missing authenticated host bridge.

An interrupted claim with no gateway journal entry stays UNKNOWN with
`gateway_not_found`; it is not automatically reissued. UNKNOWN without a broker
ID similarly still needs resolution. This avoids duplicates but is not complete
automatic crash-window recovery. The monitor's existing full-available-quantity
exit model is unchanged; this adapter adds no new sizing or trading policy.

The repository preflight still validates historical strategy fields, including
`HUMAN_APPROVAL` and a fixed position count in `scripts/verify_webui_control.py`.
A green CI run validates this branch's current contract, NOT agreement of those
legacy policy files with Katie's 15 October direction or deployed prompt state.
Their policy provenance/runtime usage needs reconciliation in the existing lane;
do not copy legacy restrictions into the controller or worker.

## Next three executable interventions

1. Night Sprints owner: export the actual queue/dispatcher/supervisor/watchdog
   source package into accessible files or the existing development lane. Retain
   test stdout and file hashes. Rebase its monitor changes onto this PR head rather
   than overwriting these fixes. Missing package bytes remain the integration blocker.
2. Engineering: connect the authenticated DeepSeek controller and supervised worker
   to this adapter and shared durable storage; exercise claim-before-journal crash
   recovery, UNKNOWN resolution, process restart and alerts before rollout.
3. Engineering + DeepSeek: install through existing backup/rollback controls,
   then record controller plan → gateway intent → broker response/position/exit →
   learning receipt. DeepSeek chooses DEMO strategy. LIVE remains disabled.

Speech acceptance remains with the audio lane: browser playback and sustained
conversation were not exercised by this GitHub sprint.

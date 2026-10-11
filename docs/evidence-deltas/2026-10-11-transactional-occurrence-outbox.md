# PR7: transactional scheduler occurrence outbox (partial crash-window repair)

**Scope:** isolated staging branch `fix/webui-occurrence-outbox-20261011`, based on PR7 `7fc6d5c7f2c17a4490b2e98e1c85ae574e6ea6c0`. Not deployed or integrated with production WebUI. This addresses the reproducible `claim_due` commit -> `asyncio.create_task` crash window.

## Delivered code

- Existing `automation_run` table serves as a durable occurrence outbox without a DB schema addition. `claim_due` commits a deterministic `scheduled:{automation_id}:{previous_due_ns}` row with status `pending` in the same transaction as advancing `automation.next_run_at`.
- Scheduler re-reads persisted pending occurrences on each poll rather than dispatching only its ephemeral `claim_due` return. If scheduler exits after claim commit but before task creation, the pending event is still available to dispatch on restart.
- Worker atomically transitions only one pending occurrence to `started` before any model/provider processing. Every ordinary `_record_run` terminal success/error updates that occurrence row via async-local ContextVar rather than appending a second history row.
- A started occurrence from a crashed or interrupted worker is **not** automatically reissued. Read-only `unresolved_occurrences` exposes stale `started` rows for explicit reconciliation. This prevents silent loss but requires an operator recovery decision for UNKNOWN execution.

## Acceptance, 11 Oct 2026

Official Open WebUI v0.11.4 container, **network none**, readonly container, fresh in-memory SQLite DB and patched model source mounted readonly:

```sh
python -m unittest discover -s tests -p test_automation_occurrence_outbox.py -v
# 3 PASS
```

Scenarios: persisted outbox recovered after claim/commit but before task creation; start claim can be taken only once and an unconfirmed started occurrence is not re-dispatched; terminal status written to original record; second poll does not create duplicate; failed transaction rolls both schedule and outbox back.

Existing PR7 focused regressions on staging checkout:
```
test_persistent_automation_router_contract.py: 5 PASS
test_persistent_automation_target_patch.py: 6 PASS
test_persistent_chat_shared_lock.py: 4 PASS (multiprocess)
```
Python compilation/diff-check passed. **18 focused tests total, 3 new.** Prior v0.11.3/v0.11.4 mocks not rerun.

## Important non-acceptance / blockers

- **NOT fully crash-replay accepted.** If a worker crashes after `started`, a model/provider call may or may not have happened. Automatic replay is forbidden until the occurrence reconciles to durable chat/run outcome; this patch leaves it marked `started` for explicit recovery and does not solve operator-free safe replay.
- Existing `automation_run.status` must now allow `pending` and `started` in consumers/UI; check all status filters and user-facing run listing. Run record's pending status is not an actual successful execution.
- Real provider/installed tool and mid-append crash fixture, manual edits, async scheduler/task startup failure, SQLite parallel worker and PostgreSQL concurrent claim tests are still required. Frozen per-occurrence target/model input, chat completion idempotency and cancellation on changed/deleted jobs are not yet proven.
- A DB transaction protects claim + pending receipt but not atomic `GET->POST` or provider invocation; model calls should never be auto retried after an ambiguous response without authoritative outcome reconciliation.
- This patch does not modify DeepSeek trading operations or its three automations, PR8/9/10/11, broker orders, secrets, production runtime, LIVE, or existing scheduling.
- Before any rollout: exclusive Engineering owner, source hash, full backup/restore, isolated actual WebUI provider/SQLite router acceptance, robust UNKNOWN-resolution contract and reversible gating.

**Status:** STAGED IMPLEMENTATION / 18 FOCUSED TESTS PASS / PRODUCTION NO-GO. Next: add deterministic completion/event correlation and safe reconciliation for `started` occurrences; run isolated v0.11.4 mock-provider two-run/restart, avoid duplicate persisted chat messages; then Engineering owner to decide release.

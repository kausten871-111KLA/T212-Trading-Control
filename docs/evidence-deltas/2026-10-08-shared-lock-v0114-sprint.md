# Shared-worker locking and v0.11.4 acceptance ? 8 October 2026

Status: tested in disposable environments; not deployed to production.

## Changes
- Added filesystem advisory locking around bound automation execution. Linux workers sharing the same local data filesystem serialize a chat through persisted completion; unrelated chats remain independent. Waits are bounded, and a killed holder releases its kernel lock.
- Detect truncated OpenAI SSE streams in bound automations so partial replies are recorded as failure rather than success.
- Forward-ported all four patch files to the tagged v0.11.4 sources, preserving upstream dictionary model defaults and async recurrence behavior.
- Added reusable source-forward-port, shared-lock, multi-worker, and version-parameterized acceptance tooling.

## Evidence
Eight real-handler tests passed on each of v0.11.3 and v0.11.4: persistent two-run replies, deleted targets, manual replay, overlap, bounded oversized history, truncated streams, HTTP failure, and timeout.
Four independent-process lock tests passed, plus a two-container real-handler test against shared disposable data.
Fifteen source contract checks passed against v0.11.4.
Authenticated v0.11.4 history survived restart; SQLite restore integrity passed. All 31 pre-existing chat histories survived the version change. The Alembic head stayed unchanged.
Rollback rehearsal passed using the pinned v0.11.3 image and the pre-upgrade disposable database, including authenticated history equality and SQLite integrity. Image digest and machine receipts are recorded alongside this report.
Production readback remained healthy v0.11.3 with the original three source hashes and two active automations. Disposable schedules remained inactive; no paid provider or broker calls were made.

## Engineering handoff
Engineering remains the sole production executor. Review all four source overlays together, back up the full production data volume, and perform the remaining production acceptance before deployment.

Remaining gates: real provider and installed tool/skill acceptance, full production-volume upgrade and rollback, manual edits during automation, mid-append application crash recovery, and durable replay/idempotency. Advisory locks are not a distributed/multi-host guarantee. SSE termination checks cover the tested OpenAI protocol. Context bounds do not bound all system/tool/knowledge output.

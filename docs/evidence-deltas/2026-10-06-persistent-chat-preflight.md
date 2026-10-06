# Persistent-chat preflight ? 6 October 2026

Status: regression harness and read-only investigation completed. The persistent-chat fix is NOT deployed. No production code, database, schedules or trading settings changed.

## Findings
- AutomationTarget lacks a chat_id field. An extra chat_id is discarded by the current model.
- Chat-target execution creates a fresh chat; message parentId and completion parent_id start null.
- Router access validation covers channels, not chat ownership. Validate ownership on create/update and at execution.
- Existing history upserts preserve content and links. Separate upserts are not atomic; concurrency and partial writes require integration tests.
- Runtime input currently contains the current prompt only. Middleware context expansion still needs inspection.
- Two jobs remain active (US OPEN/CLOSE); UK and MID remain paused. All audited jobs lack a target chat ID. Preserve cadence and enablement.
- Automation success statuses do not prove completed output or broker activity.

## Tests
Run: python3 tests/test_deployed_chat_history_contract.py --source /tmp/webui-chats-contract-20261006.py

Nine tests passed against pure functions extracted from the deployed chats.py using AST, without importing the application or accessing its database:
content preservation, parent/child links, current leaf, placeholder completion, same-ID retry, repeated append, manual branches, missing parents, null-parent behavior.

Source SHA256: aab391c385484005f929f9d807dc9b2db1f86479c5aad7227fd8771535348907

These tests establish pure history-function behavior, not database atomicity or deployed integration.

## Implementation and acceptance
1. Add explicit chat_id target schema and validation in models/automations.py; define migration for existing jobs.
2. Add owned-chat validation in routers/automations.py.
3. Update utils/automations.py to revalidate and append to the correct leaf, preserving history and message-store integrity; align completion parent_id.
4. Missing or unauthorized configured targets must fail visibly, without silent new-chat fallback. Bound model context independently of retained UI history.
5. Test overlapping runs, retries, partial writes, manual branches, deleted targets and unauthorized targets.
6. Back up source and database, stage against installed version and provide rollback. Preserve current schedules and LIVE disabled.
7. Verify two executions retain the same chat ID and prior messages, avoid duplicates, update the intended leaf and persist output after reload. Record deployed hashes before marking complete.

Isolated branch: fix/webui-persistent-chat-preflight-20261006.
Base commit: fba2f260f56065df067df16d4562f65671c7dc12.
Original checkout preserved. Reconcile newer upstream changes before implementation or merge.

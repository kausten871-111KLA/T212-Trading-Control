# Persistent target-chat patch  staged evidence (2026-10-07)

Status: **STAGED only  not deployed**

Scope: highest-priority item 1 from the 58-item 6 October WebUI handoff. All 58 items remain authoritative; this change does not close or reorder the remainder.

## Runtime evidence

- 2026-10-07T03:09:23Z: strict-host-key SSH control succeeded (SSH_EXIT=0) after the required process-local ProgramData repair.
- Isolated worktree was clean at commit 17bf01c664659ba1bbc4b50642d2fa8042616944; no worktree lock or active writer was found.
- 2026-10-07T03:10:05Z: container open-webui healthy on image ghcr.io/open-webui/open-webui:v0.11.3.
- Live source hashes before this staged change:
  - models/automations.py: b4cd79307d1bef9762b320ca6afcaeeaf0f4c8d7734434ea06d6ae7491bc90da
  - routers/automations.py: 300fecc536271b1d3464a76321383c145fe91c547e6c691ba1b01bfd4ebdffc8
  - utils/automations.py: 8a319c0118aa77607316098b5e338702e15db47b75929a290fe9a6774d0df00f
- Live source still creates a fresh UUID chat per non-channel run. No automation has a persistent chat_id.
- Active cadence: US OPEN and US CLOSE. Paused: US MID, UK OPEN, UK CLOSE. This patch does not change schedules.
- No T212 order, broker write, provider call, database write or production WebUI file change was performed.

## Staged change

Exact v0.11.3 deployed sources were copied into patches/openwebui-v0.11.3/ and changed to:

1. accept target.chat_id and target.context_messages;
2. verify the target belongs to the automation owner before completion handling;
3. reject missing/foreign targets and invalid current leaves;
4. append from the current leaf via the existing backend completion path;
5. supply only the active branch, capped at 50 non-empty messages and 32,000 characters;
6. retain fresh-chat behavior when chat_id is absent.

## Validation

- Python byte-compilation: passed.
- tests/test_persistent_automation_target_patch.py: 6 pure tests passed.
- tests/test_deployed_chat_history_contract.py against the exact live models/chats.py: 9 tests passed.
- git diff --check: passed.
- Production deployment/integration acceptance: not run; therefore not claimed.

## Deployment gate

Before production replacement: review the staged diff, run a disposable WebUI integration with a same-owner target and a foreign-owner negative case, back up the three live automation sources plus webui.db, then deploy only the reviewed model and utility files. After restart, require health success, two no-order appends to one test chat, intact earlier history, bounded request context, and rollback rehearsal. Keep DEMO/LIVE controls and the OPEN/CLOSE cadence unchanged.

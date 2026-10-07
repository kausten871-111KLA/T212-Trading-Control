# Persistent-chat ownership integration evidence  7 October 2026

Status: **STAGED, not deployed**

Scope: WebUI v0.11.3 persistent target-chat patch. No production database write, provider call, broker call, or order operation was performed. The 58-item 6 October handoff remains the authoritative backlog; this delta changes no item scope or status beyond the persistent-chat engineering subtask.

## Change

The exact deployed v0.11.3 automations router was copied into the patch bundle and changed to validate a target chat with `Chats.get_chat_by_id_and_user_id(...)` before automation create or update. Missing or foreign chat targets fail closed with HTTP 404. Unbound chat targets remain valid. Execution-time ownership validation remains in the previously staged executor patch.

## Disposable API/DB integration

Evidence timestamp: `2026-10-07T12:43:51Z`

Environment:

- Container: `open-webui-persistent-chat-it-20261007`
- Image: `ghcr.io/open-webui/open-webui:v0.11.3`
- Bind: `127.0.0.1:38080`
- Separate data directory: `/home/katie/webui-persistent-chat-integration-20261007`
- Staged model/router/utils mounted read-only
- Offline mode; OpenAI and Ollama disabled
- Disposable local users and credentials only

Results:

| Scenario | Expected | Observed |
|---|---:|---:|
| Same-owner create with target chat | 200 | 200 |
| Foreign-owner create with target chat | 404 | 404 |
| Missing target-chat create | 404 | 404 |
| Unbound automation create | 200 | 200 |
| Foreign-owner update to target chat | 404 | 404 |
| Same-owner update to target chat | 200 | 200 |

SQLite audit saved only `it3-same-owner-updated` and `it3-unbound`; invalid foreign/missing records were absent. Sanitized machine result remains at `/home/katie/webui-persistent-chat-integration-20261007/integration-result-final.json`.

## Regression evidence

At `2026-10-07T12:46:24Z`:

- 6 persistent target/executor tests passed.
- 5 router contract tests passed.
- 9 exact deployed chat-history contract tests passed.
- `py_compile` passed for staged model/router/utils.
- `git diff --check` passed.
- Production `open-webui` remained `running healthy` on v0.11.3.
- Production hashes remained the unpatched baseline:
  - model: `b4cd79307d1bef9762b320ca6afcaeeaf0f4c8d7734434ea06d6ae7491bc90da`
  - router: `300fecc536271b1d3464a76321383c145fe91c547e6c691ba1b01bfd4ebdffc8`
  - utils: `8a319c0118aa77607316098b5e338702e15db47b75929a290fe9a6774d0df00f`

Cadence remained unchanged: US OPEN/CLOSE active; US MID and UK OPEN/CLOSE paused. This evidence does not prove provider-backed two-run append/reload behaviour; production deployment remains gated on that acceptance and backup/rollback execution.

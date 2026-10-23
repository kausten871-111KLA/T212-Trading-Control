# Trading Operations — 23 October 2026 Midday Engineering Handover

## Scope and evidence
- **Single owner model:** `trading-operations--deepseek`. Model ID is stable across WebUI chat resets.
- **Existing production services:** `deepseek-phase.service` and `deepseek-command-bridge.service`. Both observed active. Do not install another broker or schedule daemon.
- **Existing WebUI automations:** five active jobs, IDs verified against production SQLite. Do not create replacements.
- **Current code:** draft PR #21 only. Host development checkout `0afb7d1` has unrelated uncommitted Twelve Data changes; never reset or overwrite them.
- **Broker:** T212 DEMO only; LIVE disabled. No model-task handler directly places orders.
- **Data:** FinMem outcomes remain unverified pending a fresh authenticated T212 DEMO history read.

## Newly staged components
1. `model_task_queue.py`: durable SQLite task queue, future UTC times, stable dedupe, lease ownership, retries, completion, cancellation.
2. `model_task_bridge_adapter.py`: host-context-only model task ingress.
3. `model_task_host_commands.py`: trusted host token-to-ingress adapter.
4. `host_command_bridge.py`: optional **/model-task** route on the **existing** bridge Unix socket. The route is disabled unless `CONTABO_MODEL_TASK_TOKEN` is separately provisioned (minimum 48 characters). It does **not** accept the general `X-Bridge-Token`; it requires `X-Model-Task-Token`. Its only actions are create/status/cancel. No inference or broker calls.
5. `model_task_worker_adapter.py`: explicit model inference callback injection, light/pro routing, provider usage receipt. Production routing IDs verified in WebUI: `deepseek-flash` and `deepseek-v4-pro`. The Trading Operations owner model has its own instructions/tools; do **not** assume calling these provider model IDs directly carries those bindings. Preserve the owner model's tool context when installing a host inference adapter.
6. `webui_dst_migration.py`: five-job reversible Oct 26–30 manifest.
7. `webui_dst_api_client.py`: verified WebUI v0.12.3 routes `GET /api/v1/automations/{id}`, `POST /api/v1/automations/{id}/update`. Requires an authorized user Bearer token. Uses exact AutomationForm fields, verifies all five jobs before writes, preserves prompt/target/metadata, verifies persisted RRULE and next-run nanosecond timestamps, and rolls back on partial failures.

## Before any production installation
1. Backup the production WebUI SQLite via its SQLite online backup interface; verify `integrity_check`. Back up the existing runtime DB and bridge service configuration. Record the five original automation IDs, RRULEs and next-run times in a secure local manifest. Do not publish credentials.
2. Install only reviewed PR changes into the existing runtime after merging/review. Run offline tests first; do not deploy the dirty development checkout wholesale.
3. Generate a **dedicated model-task token** on the host and store it in the existing bridge's secure service environment. Do not reuse the general command token. The model-specific WebUI tool must be bound **only** to `trading-operations--deepseek`, not arbitrary chats/models. Validate WebUI tool binding independently. Restart the existing bridge only during a controlled window, and verify old `/command` behavior remains unchanged.
4. Register the task worker callback inside the **existing** supervised service; configure actual authenticated WebUI inference transport and preserve Trading Operations instructions/tools. No new broker and no extra autonomous order executor. Test one no-cost synthetic task across two different WebUI chats and a service restart, with exactly one completion receipt and zero broker calls. Then test one explicitly approved low-cost model inference and record usage. No Pro calls without explicit deployment authorization.
5. Enable model task scheduling only after the full end-to-end acceptance. The staged queue/bridge alone do **not** make DeepSeek autonomous.

## Daylight-saving cutover
**Do not change Friday 23 October trading jobs while Friday's session is active.** UK switches to GMT on Sunday 25 Oct; New York remains EDT until Sunday 1 Nov.

| Existing job | Oct 26–30 UK target | Normal UK clock to restore from Nov 2 |
|---|---|---|
| Morning Research Runner | 12:00 | 13:00 |
| US CONTROLLER | 13:00 | 14:00 |
| US OPEN | 13:35 | 14:35 |
| US MIDDAY | 16:30 | 17:30 |
| US CLOSE | 19:35 | 20:35 |

The update API is authenticated and permission-checked. The five-job plan must be built from a current WebUI snapshot; update/restore is a controlled operation. Confirm `next_runs` for Monday 26 Oct, and after restoring confirm Monday 2 Nov. The DAILY research job also runs on weekends in its **existing** schedule; this sprint does not silently change that cadence. If no authorized user token or verified UI session is available, **do not write** schedules. Escalate exact blocker rather than direct SQLite modification.

## Known acceptance blockers
- Dedicated model-task token and WebUI tool binding are not yet provisioned.
- Existing `deepseek-phase.service` does not yet invoke the staged `run_existing_worker_cycle` callback. No real background DeepSeek inference has occurred.
- WebUI user Bearer token for authenticated automation updates is not present in this engineering handoff; production DST schedule change remains pending.
- Fresh authenticated broker history and causal research-decision linkage still required for FinMem.
- Contabo recovery console is unavailable; postpone UFW/SSH/cloudflared/OS privilege changes.

## Verification claims
Use only exact test output and GitHub CI for the current PR head. All testing is isolated, no broker orders and no paid model calls. This document is a staged deployment plan, not a production acceptance certificate.

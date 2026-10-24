# Phase service rollout boundary

The service dispatches durable phase events to controller_instruction. It does
not itself call a model or broker. `trading_ready=false` is intentional evidence
of missing host wiring, not a restriction on DeepSeek's authorised DEMO strategy.

Verified source seam in installed WebUI 0.11.4:
`open_webui.utils.automations.execute_automation` resolves the stored owner,
checks feature permissions, builds an automation-scoped token, resolves the
model's tools and invokes `app.state.CHAT_COMPLETION_HANDLER`.

`WebUIAutomationIngress` is a host-callable adapter for that path. Its loader
and permission callback must use the actual installed WebUI models/permissions;
do not expose caller-supplied callbacks, user IDs or schedule dates as credentials.
The installed AutomationTable does NOT have `get_automation_by_id`; bind the
verified `Automations.get_by_id` method, as `installed_webui_ingress` now does.
Preserve the original scheduled occurrence on retries. Invoke exactly one
completion pipeline; do not run both the legacy path and a new outbox consumer.

Outstanding before trading activation:
- Connect authenticated ingress to original existing phase invocation.
- Shared durable DB access between WebUI container and supervised process.
- Consume PHASE_EVENT through the existing model/tool pipeline, retain the plan,
  acknowledge actual model completion and return reconciled outcomes to DeepSeek.
- Inject existing configured Alpaca tool and DEMO gateway/journal into workers;
  do not create another broker client or copy credentials into this checkout.
- `IntentReconciler` handles awaiting_verification receipts; wire it to that same
  gateway. Partial/UNKNOWN outcomes remain unresolved. A recovered event marked
  done is a processing result, not profitability or a complete trading cycle.
- Validate full process restart and end-to-end broker receipts with this wiring.

Installation (user service; source checkout must be pinned and clean):
1. Put reviewed source at ~/t212-runtime-service, detached at reviewed commit.
2. python3 -m runtime.deepseek.service --db ~/.local/state/deepseek-runtime/trading_state.db --migrate
3. install -m 600 deploy/deepseek/deepseek-phase.service ~/.config/systemd/user/deepseek-phase.service
4. systemctl --user daemon-reload
5. systemctl --user start deepseek-phase.service
6. Inspect status and journal, restart and stop for acceptance.

Do not enable the unfinished service as proof of trading readiness. Boot/logout
persistence requires a deliberately configured service account/user lingering;
`loginctl show-user katie -p Linger` was `no` on 18 October. No schedule change.

Rollback: `systemctl --user stop deepseek-phase.service`; disable if enabled.
Retain the DB/online backups. Restore source or database only after stopping
writers and verifying the selected backup. Existing WebUI remains unchanged.

# P1 authenticated WebUI scanner-stage receipt provenance audit ? 7 November 2026

**DRAFT / documentation-only / no deployment.** Isolated branch based on draft PR #25 at e3f44dc485f7bafa47cbe4376a52c057fd530a12. PRs #21?#25 were checked open, draft and unmerged at audit time. Issue #20 remains the broader operations register. No external model, broker, production SQLite or WebUI runtime invocation was made.

## Source-verified paths and boundaries

1. `runtime/deepseek/model_task_phase_registration.py:13-45`: SupervisedModelTaskCycle is a **factory for an injected trusted invoke_model callback**, not a working WebUI model transport. It requires an actual callable, owner context, explicit worker ID and model routes. This source does not supply the callback.
2. `runtime/deepseek/service.py:55-67,104-125`: PhaseService has an optional model_task_cycle and calls it only when injected. The default is absent. The service's schema setup installs ModelInvocationGate with an authorizer and terminal verifier that always deny; schema installation does not authenticate or invoke a model.
3. `runtime/deepseek/model_invocation_gate.py:16-25,55-91,100-150`: durable claim and terminal completion cover an authenticated **PHASE_EVENT controller instruction**, requiring a host principal, valid automation/market-date dispatch linkage and an independent verify_terminal callback. They are not scanner candidate-stage receipts. Claim persists before model I/O; a crash leaves UNKNOWN, not automatic retry authority.
4. `runtime/deepseek/model_terminal_ack.py:9-44`: ModelTerminalAcknowledger consumes a terminal receipt already verified by the host, tied to invocation/chat/message IDs, then acknowledges a controller instruction. It neither creates stage receipts nor supplies a host verifier.
5. `runtime/deepseek/webui_run_observer.py:40-82,85-115,180-245`: the observer reads **existing completed scheduled WebUI automation runs** (automation_run + chat_message metadata) and stores webui_run_receipt keyed by scheduled run ID. It checks the configured model/tool context and matched tool outputs, but its evidence is a **scheduled run** not a per-batch INVESTIGATOR or DECISION completion. Its no_duplicate_model_invocation flag describes observational behaviour, not a scanner-stage model call.
6. `runtime/deepseek/scanner_candidate_consumer.py:349-415`: record_verified_stage requires a host-supplied receipt_lookup callable returning independently verified source=authenticated_webui_host_terminal, receipt ID, exact stage, batch ID, complete candidate IDs and terminal=completed; it rechecks the owned live lease and INVESTIGATOR-before-DECISION order. **No concrete authenticated lookup implementation or actual invocation-to-receipt mapping was found in the inspected staged runtime/deepseek and openwebui/tools Python sources.** A synthetic callback in unit tests is not production evidence.

## Missing host contracts / blockers (do not assume they exist)

- Authoritative WebUI owner-context invocation entrypoint: function/module, authenticated principal/owner scope, model route and explicit approved research-only tools; no independent inference worker may be invented.
- Independent terminal stage receipt store and resolver: durable invocation ID, batch ID, candidate ID list, stage, chat/message IDs, terminal status, timestamp, host principal, replay protection and verification of original WebUI completion; no caller-supplied JSON/boolean can substitute.
- Durable invocation reservation and reconciliation **per actual stage and retry** with UTC-day cap, unknown-after-crash handling and provider-wide cost accounting; PR #25 documents the gap but implements no correction.
- DeepSeek methodology-owner candidate admission policy, exclusions, repeat-alert handling, prioritisation and bounded per-cycle maximum.
- Offline tests for failed/missing stage, restart, unknown invocation and stale lease; supervised non-order acceptance, rollback and merge dependency review before any activation.

## Production preservation check (read-only)

- Production checkout: detached 6ef37175fe8e5cef5c8560b44dd3d02025d17105, 13 modified/untracked entries (unchanged from previous review).
- SHA256 scanner_read_commands.py: 878b8ef3d67b997368ce33f98a41f913c68399401acb29e1b86f4d7bf16beda6.
- SHA256 host_command_bridge.py: 1ed6ed3a8fd61bcb72b2cd96a43fbf70080c56a1bd6449241ea6e5727eea49d6.
- SHA256 openwebui/tools/contabo_command_bridge.py: 3ea92eb53e4e9fc71a2cb2c6b8557ac0c8f62fe44768a152cb351ae45d60fa7b.
- No production write, model call, broker call, service/schedule change or cursor advance. Default model budget remains zero.

**Decision:** Gate stays CLOSED. Next safe task is purely offline crash/restart and missing-stage acceptance tests using synthetic, clearly labelled receipts, not an authenticated live end-to-end acceptance. The existing 07:30 Trading & WebUI sprint remains independent.

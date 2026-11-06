# P1 scanner-to-DeepSeek bounded review ? 6 November 2026

STATUS: DRAFT ONLY. Unmerged, undeployed, model-call budget 0. No polling, model invocation, broker operation or service change implemented.

## Revision and production checkout (read-only inspection)

PR #22: open/draft/unmerged, branch feature/scanner-consumer-foundation-20261105, head 8cb94c083a9368c1907f5b7a75052cf71b8bd5d8. Based on PR #21, also open/draft/unmerged, branch feature/t212-runtime-integrated-stage-20261018, head 99ad4039a3098f02feacace335288196c2f240a5.

Live checkout: /home/katie/t212-runtime-service, detached commit 6ef37175fe8e5cef5c8560b44dd3d02025d17105, with 13 modified/untracked entries. The live checkout and its Git metadata are deliberately untouched. Changes were made in an independent clone at /tmp/t212-p1-scanner-sprint-20261106 on the new isolated branch feature/p1-scanner-handoff-reviewed-20261106, forked from exact PR #22 head.

Deployed scanner reader copied to staged source. Exact host and WebUI source bytes saved separately under docs/source-snapshots/20261105/ for review; additive scanner changes preserve PR 21 model-task features:
- runtime/deepseek/scanner_read_commands.py : 878b8ef3d67b997368ce33f98a41f913c68399401acb29e1b86f4d7bf16beda6
- runtime/deepseek/host_command_bridge.py : 1ed6ed3a8fd61bcb72b2cd96a43fbf70080c56a1bd6449241ea6e5727eea49d6
- openwebui/tools/contabo_command_bridge.py : 3ea92eb53e4e9fc71a2cb2c6b8557ac0c8f62fe44768a152cb351ae45d60fa7b

Other live source SHA-256:
- runtime/deepseek/webui_run_observer.py : 1493831137bb38d94d60e6e9afdc3855d061bb7871dbf8c6059e7fc1803a70ec
- runtime/deepseek/controller_worker.py : 89034c0bc75adab9e40b7faf24f6d65308b338a2e5a8f5cd11cffcc4580b2791
- runtime/deepseek/controller_phase_bridge.py : 7666a171d6c235819e9d1e580c49471daea121795ee9e944bfcab7e270f05e60
- runtime/deepseek/controller_ack.py : 78c6f94c763da5ebc4eee77bdc090aeb6420f28280ad6c878d90e7700b94696b
- runtime/deepseek/model_invocation_gate.py : 81a335dfe169f6604e3547310452e610b99817739c4faaf30a66c81320b168c0
- runtime/deepseek/model_terminal_ack.py : 8a3d5aac07036a8fbe9bd5a7d3b3f7a261b1d7a60eea766060bfa7b5bf6472f4
- runtime/deepseek/service.py : a51ef6d4d6e1724fd1144e9b737864ea222f18aee21ded649a14a594583778ce
Staged branch service.py is materially different, SHA-256 27e653d274714aeff2eb379938191dabaeda263502f3bd9d32c22fd2c316e0e5. Do not assume staged service matches active production.

No env contents, tokens, personal chat text, trading data or broker records were copied or printed.

## Existing interface actually inspected

- The deployed scanner reader supports scanner_candidates(cursor=-1, limit=5) and scanner_health(). Scanner candidates are read from the scanner SQLite with mode=ro and query_only=ON. Cursor -1 bootstraps the newest bounded page; cursor 0 starts history; subsequent nonnegative cursor returns strictly later IDs. Host limit is 12. Returned records contain IDs, signals, timestamps, price and market observations with max_id_at_read and next_cursor. Reading does not mark anything delivered.
- Host command bridge permits these fixed commands on its existing authenticated Unix socket, and the WebUI Tool contabo_command exposes command, cursor and limit. Source snapshot is Git review material, not automatic deployment of WebUI tool registrations.
- Alpaca IEX observations are not consolidated SIP data and are not verified trade signals.

## Authenticated WebUI delivery and genuine receipt audit

- Staged runtime/deepseek/service.py defines PhaseService(model_task_cycle=...) but normal main leaves the hook unregistered. Staged model_task_phase_registration.py requires a separately injected trusted invoke_model callable.
- Staged ModelInvocationGate claims PHASE_EVENT model invocations and expects a host-provided terminal verifier, but does not itself invoke models or produce two candidate-specific INVESTIGATOR and DECISION receipts.
- Existing VerifiedScheduledRunObserver only inspects SAVED EXISTING WEBUI AUTOMATION RUN metadata and links it to a controller PHASE_EVENT. Its webui_run_receipt proves a scheduled phase run, not separate scanner INVESTIGATOR/DECISION completions.
- ControllerPhaseBridge, ControllerPhaseWorker, ModelTerminalAcknowledger and PHASE_DISPATCH are not evidence of scanner candidate-stage processing. A transport 200, model text or caller-supplied booleans cannot substitute for two host-verified terminal receipts.
- No inspected deployed or staged interface establishes a host-authorised invocation of INVESTIGATOR then DECISION with independently provable candidate-specific receipt IDs. This is a genuine integration blocker. Do not invent an API token, provider client, stage message, broker writer, scheduler or receipt.

## Reviewed ledger improvements in this isolated branch

- Separate persisted stage evidence in consumer_stage_receipt, indexed by (batch_id,stage) with unique receipt_id.
- record_verified_stage requires a trusted host-injected receipt_lookup callback; absent by default, fails closed. Its evidence must bind source, stage, receipt ID, batch ID, full candidate ID list and terminal=completed. The host must implement an independent authenticated lookup backed by real WebUI records; passing this schema as chat text is not proof.
- DECISION cannot be recorded before INVESTIGATOR or with the same ID. Cursor acknowledgement checks two *persisted* stage receipt rows, complete candidate set, current worker/lease and unchanged cursor, all inside the transaction. Caller-supplied ack booleans alone never advance a cursor.
- At one cursor, no new *different* page can stage while another batch is unacknowledged; exact same hash-based batch ID remains idempotent.
- Expired exhausted attempts are marked failed rather than remaining stranded in flight.
- Bounded batches, retry/backoff, stable hash-based batch ID, restart recovery and default zero inference budget are retained. No model call is enabled in this branch.

## Explicit integration and methodology gates

1. Methodology owner / DeepSeek must approve a deterministic candidate-eligibility predicate, including accepted evidence combinations, stale/halts exclusions, prioritisation, repeat alerts, and maximum admitted per cycle. NO numeric threshold has been invented in this branch.
2. Owner must set an explicit daily budget for ACTUAL model invocations, considering two stages and retries. Default remains 0. The foundation currently reserves one budget unit per claimed batch, which is NOT sufficient proof of two individually budgeted model calls. Reconcile this before any nonzero budget.
3. Engineering must independently identify the authorised WebUI owner-context invocation entrypoint and the persistently queryable INVESTIGATOR and DECISION terminal receipts, bound to a stable batch ID and complete candidate IDs. A trusted receipt_lookup can be injected only after its authority and data are validated.
4. Reuse the existing supervised phase worker injection path only if verified; do not add new schedules, model clients or broker connections. Require non-order acceptance including retries, crashes and authenticated dual receipts before any deploy.
5. Keep production cursor untouched and outbox_delivered_to_model false until real proof. Staging is not activation.

## Tests actually performed

Offline testing: 10 new synthetic tests (8 ledger and 2 bridge dispatch), plus 16 existing HTTP bridge, 8 model-task WebUI tool and 8 Twelve Data bridge regression cases, 42 passed in total. Eight SQLite cases included: zero budget, page dedup/conflict, stage verification plus restart, forged evidence rejection, stale lease recovery, exhausted retry terminal state, retry backoff plus restart, empty/invalid/oversized page. Synthetic receipt lookup test doubles are NOT real WebUI receipt evidence. Also Python bytecode compilation and git diff --check in isolated clone. No external DeepSeek/LLM requests, no broker writes/orders, no service restart, no schedule or production checkout changes.

## Source-compatibility review
The draft PR 21 host contains additional model-task functionality absent from deployed host. Staged files retain those functions and only add scanner commands. Deployed versions are retained as source-only snapshots, not executable replacements. WebUI-dependency tests ran in a read-only isolated Docker container with networking disabled.

Scanner reader original byte snapshot is preserved as a base64 text file at docs/source-snapshots/20261105/deployed_scanner_read_commands.py.snapshot.b64, SHA-256 of decoded bytes: 878b8ef3d67b997368ce33f98a41f913c68399401acb29e1b86f4d7bf16beda6. The staged executable reader differs only by removal of the original trailing empty CRLF line, for a clean Git whitespace check. Host and WebUI snapshots are source text with original bytes.

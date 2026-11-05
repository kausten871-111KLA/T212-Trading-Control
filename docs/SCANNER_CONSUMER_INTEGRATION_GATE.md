# Scanner consumer integration gate

**Status: ledger foundation staged; no automatic polling or model delivery is active.**

This note records the remaining integration work for the scanner candidate consumer. It is intentionally not a service-installation guide.

## Current safe boundary

- The scanner and its authenticated WebUI pull commands are deployed on Contabo, according to the 5 November 2026 operational report.
- The deployed scanner reader currently lives in the Contabo working checkout, which was observed with unrelated local modifications. Do not overwrite, reset, or deploy from that checkout.
- The Git branch carrying this ledger is based on the staged runtime branch, which does not contain the deployed `scanner_read_commands.py` source or the current scanner tool edits.
- `PhaseService` supports an optional trusted `model_task_cycle` callback, but its normal service entrypoint leaves that callback unregistered. The separate model-task route is not evidence of an INVESTIGATOR/DECISION invocation.
- The ledger has no polling loop or model transport. Its daily model-call budget defaults to zero; cursor movement requires a batch acknowledgement with distinct INVESTIGATOR and DECISION receipt IDs.

## Required integration work

1. **Reconcile source:** create a reviewed, versioned snapshot of the exact deployed scanner reader and bridge tool edits. Preserve the live checkout and its local changes. Record hashes and compare its interfaces with this branch before integration.
2. **Bind one authenticated read path:** call the existing `scanner_health` and bounded `scanner_candidates(cursor, limit)` command through the existing authenticated bridge. Keep scanner DB access read-only. Do not add a shell command or accept model-supplied filesystem paths.
3. **Persist before delivery:** stage each bounded page in the separate consumer ledger. Re-read the persisted cursor after restart. Do not advance on poll, staging, model timeout, partial batch, or lost acknowledgement.
4. **Use the existing DeepSeek pipeline:** identify the authenticated WebUI invocation and saved-run/receipt mechanism that delivers INVESTIGATOR then DECISION. Reuse it once. Do not add a duplicate schedule, chat automation, direct provider client, or second invocation path.
5. **Add an agreed cheap admission rule:** keep polling cheap and independent of model calls. Define the “warrants investigation” filter with the existing trading methodology owner; until that rule and a bounded UTC-day budget are explicitly configured, leave model inference disabled.
6. **Persist independent receipts:** store both stage receipt IDs. A combined boolean, transport success, or fabricated caller value is not proof that either stage completed.
7. **Exercise recovery before activation:** on a disposable database, verify bootstrap cursor semantics, duplicate page idempotency, retry/backoff, expired-lease recovery, budget exhaustion, process restart, and strict acknowledgement. Then perform supervised non-order end-to-end acceptance with call and broker counters.
8. **Operator gate:** only after source reconciliation and acceptance should a reviewed deployment plan cover the existing worker, backup, rollback, and status reporting. Preserve existing schedules, T212 DEMO controls, and LIVE-disabled state.

## Current code boundary

`runtime/deepseek/scanner_candidate_consumer.py` supplies the durable ledger and contracts only. It does not fetch candidates, decide eligibility, invoke DeepSeek, create schedules, or call a broker. Do not describe the scanner-to-INVESTIGATOR-to-DECISION handoff as complete until independent receipts and cursor advancement are observed in the persistent ledger.

# Real-handler persistent-chat recovery sprint ? 8 October 2026

Status: TESTED IN ISOLATION / STAGED. Production deployment: NO.
Base: ca848d658d2471c64058508b8a3f0244af366f30.
Version tested: standard Open WebUI v0.11.3.

## Implemented
- Deterministic localhost OpenAI-compatible mock, with SSE, failure and delay modes.
- Real automation/completion API harness and resilience tests, private short-lived test authentication, synthetic request captures and automatic provider-config restoration.
- Chat automation success waits for persisted assistant done=true and checks message errors first. Timeout cancels only completion task IDs returned for that execution.
- Bound-chat automations serialize through a process-local chat lock until streamed persistence finishes.
- Trusted server Request.state flag prevents middleware from replacing the bounded automation history payload with the complete database history. Ordinary API callers retain standard DB replay.

## Defects reproduced before correction
1. Provider HTTP 500 was recorded as automation success.
2. Overlapping run 2 omitted run 1's reply from provider context.
3. A 70-message fixture bypassed the executor context limit: middleware reconstructed the whole saved branch.

The third defect requires a FOURTH patched file: utils/middleware.py. The older three-file deploy/backup instructions are now incomplete for this candidate.

## Acceptance results
Six real-handler tests passed together:
- Two runs retain the same chat, completed replies, seed and coherent links; second request contains first reply.
- Deleted target yields error and zero provider calls.
- Overlap preserves both replies and second-run prior-reply context in one process.
- Oversized fixture retains all 72 stored messages, while outbound prior history is 32 messages / 32,000 characters (within 50-message hard cap).
- Provider HTTP 500 yields an error run, not success.
- Completion timeout yields an error run.

Restart proof passed: authenticated API history is identical after application restart. SQLite backup restored into a separate file passes integrity_check and retains that same history. This is a database restore proof, not a complete production rollback rehearsal.

Existing pure regressions: 6 target/executor, 5 ownership-router and 9 deployed-history tests passed. Syntax checks and git diff --check passed.

Machine receipts remain private in the disposable data directory:
two-run-acceptance-result.json, resilience-acceptance-result.json, restart-acceptance-result.json.
Provider captures contain synthetic fixture messages only; authorization headers are never captured.

## Reproduce
Run the mock INSIDE the disposable container; host loopback is not container loopback.
It binds 127.0.0.1:38181 and must have a writable capture path.
The runner validates the explicit disposable container, loopback application endpoint, matching data bind and inactive schedules before generating private test authentication.

    python3 tools/run_disposable_chat_acceptance.py --data-dir /path/to/webui-handler-integration-YYYYMMDD
    python3 tools/verify_disposable_chat_restart.py --data-dir /path/to/webui-handler-integration-YYYYMMDD

Runner default application endpoint: loopback 38081. Existing initial disposable endpoint 38080 is supported by the tests, but the guarded candidate runner deliberately targets 38081.

## Remaining deployment gates
- Process-local serialization is NOT a distributed/multi-worker lease, does not prevent manual-chat concurrency, and does not implement durable replay idempotency.
- Partial stream disconnect, crash during append, manual edits during automation, foreign-owner execution after target reassignment, and distributed contention remain separate acceptance requirements.
- History bounds do not establish a bound on total system prompts, knowledge, tool schemas or tool-generated content.
- Timeout cancellation is implemented for returned task IDs; the timeout test proves truthful run status, not all remote cancellation races.
- Channel automations are outside this corrective change.
- Production backup and complete app rollback rehearsal remain required before deployment.
- Forward-port FOUR custom files onto v0.11.4, preserving upstream recurrence changes; do not overlay the v0.11.3 bundle.

Engineering retains production ownership. This sprint used separate code/data targets and did not deploy to production, contact brokers, change production schedules or spend external-model credits.

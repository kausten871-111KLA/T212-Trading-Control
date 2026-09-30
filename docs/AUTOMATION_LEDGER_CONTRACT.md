# Automation Run Ledger and Health Contract

## Purpose

Give Executive Orchestra and the four active workspaces one durable record of
what each worker actually did. This removes dependence on chat memory and
prevents “completed” claims without evidence.

This component records runs. It does not create schedules, launch workers,
publish content or submit broker orders.

## One record per state transition

Each JSONL record includes:

- run and workflow identity;
- workspace;
- start, end and heartbeat timestamps;
- status and attempt number;
- input and output references;
- evidence;
- model role and tool IDs;
- estimated/actual cost;
- bounded error summary and retryability;
- approvals;
- next action;
- T212 safety state where applicable.

Records are append-only, locked during writes, flushed to disk and created with
mode `0600`.

## Health interpretation

| Ledger state | Health |
|---|---|
| RUNNING with fresh heartbeat | RUNNING |
| RUNNING beyond freshness threshold | STALE |
| SUCCEEDED | HEALTHY |
| FAILED or BLOCKED | DEGRADED |
| CANCELLED | STOPPED |

The default stale threshold in the helper is 15 minutes. A worker-specific
threshold may be supplied by its deployment configuration.

## Security

Ledger records must contain references, not credentials or raw secret values.
The validator rejects common token/password forms. API keys remain only in
server-side secret storage.

For `t212-demo`, every record must state:

- environment: `DEMO`;
- live trading: `false`;
- order mutation: `false`.

A record violating any of these is rejected before it can be appended.

## Failure and retry behaviour

A retry creates a new record with an incremented attempt. It must not overwrite
the failed record. Non-retryable errors, exhausted attempts, ambiguous external
writes, missing approvals and safety failures become `BLOCKED` with the
smallest next human or engineering action recorded.

The ledger never performs a retry itself.

## Verification

From a clean checkout:

```bash
python -m unittest discover -s tests -p 'test_automation_ledger.py'
```

Before deployment, write/read a temporary ledger, confirm mode `0600`, then
confirm stale-heartbeat detection and the T212 DEMO safety rejection tests.

## Deployment and rollback

Proposed persistent location:

```text
/opt/webui-control/state/automation-runs.jsonl
```

Create a dated backup before changing the deployed worker configuration. To
roll back, stop ledger integration in the workers and restore the previous
configuration. The append-only ledger remains evidence and must not be deleted.

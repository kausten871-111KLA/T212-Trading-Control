# Canonical Morning, Evening and Event Handoffs

## Purpose

Give Executive Orchestra one compact, evidence-backed format across:

- T212 Trading Operations;
- Apps / Plugins / Bots;
- You Heal Content Production;
- Books & Publishing.

The handoff is generated from validated automation-ledger records. It does not
infer work from chat, create content, publish, schedule, spend money or mutate a
broker account.

## Sections

Every handoff contains:

1. verified run totals;
2. completed outputs;
3. evidence;
4. current and stale workers;
5. blockers and the smallest next action;
6. approvals and their state;
7. prioritised next actions;
8. artifact references;
9. rollback reference;
10. T212 safety state where relevant.

An empty period explicitly says that no verified runs were recorded. It never
turns absence of evidence into a progress claim.

## Cadence

- `MORNING`: what is ready, blocked or awaiting approval at the start of work;
- `EVENING`: what completed, failed or remains active;
- `EVENT`: material failure, safety halt, deployment result or human-only
  blocker.

Cadence generation remains owned by the existing project controls. This module
does not create or modify schedules.

## Ownership

The deterministic compiler assigns system failures to `SYSTEM`. Before a
human-facing handoff is issued, Executive Orchestra may change ownership to
`KATIE` or `EXTERNAL` only when the evidence identifies a genuinely
human-only or third-party action.

## T212 boundary

Every T212 handoff carries an explicit safety banner:

- DEMO only;
- LIVE trading disabled;
- order mutation disabled.

This overnight handoff layer reports technical readiness only and cannot
propose, submit, modify or cancel an order.

## Verification

From a clean checkout:

```bash
python -m unittest discover -s tests -p 'test_shift_handoff.py'
```

The tests verify workspace/period isolation, honest empty periods, blocker and
approval preservation, stale-worker detection, and the T212 safety banner.

## Deployment and rollback

The component is additive and has no live effect until a worker calls it.
Before integration, retain the existing WebUI database/tool-table backups and
record the previous handoff configuration. Rollback by disabling compiler
invocation and restoring the prior configuration; preserve generated handoffs
as audit evidence.

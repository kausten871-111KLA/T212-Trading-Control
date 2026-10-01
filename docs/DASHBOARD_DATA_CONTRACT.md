# Executive Dashboard Data Contract

## Purpose

Provide one compact, read-only snapshot across the four active WebUI
workspaces. This is the data foundation for a future WebUI home dashboard; it
does not change the interface or deploy a service.

## Panels

The snapshot always contains, in a fixed order:

1. T212 Trading Operations;
2. Apps / Plugins / Bots;
3. You Heal Content Production;
4. Books & Publishing.

Each panel exposes the latest verified handoff, run totals, blockers, pending
approvals, next actions, artifacts and last-handoff time. A missing handoff is
shown as `NO_DATA`, never inferred as success.

## Overall health

- `HEALTHY`: verified handoffs with no failures, stale workers, blockers or
  pending approvals;
- `ATTENTION`: blocker or pending human approval;
- `DEGRADED`: failed run or stale worker;
- `NO_DATA`: no verified handoff exists.

Actual metered costs are grouped by unit (`CREDITS`, `TOKENS`, `GBP` or
`USD`) without inventing conversions.

## T212 safety

The dashboard always exposes:

- environment: `DEMO`;
- LIVE trading: `false`;
- order mutation: `false`.

An input handoff that contradicts this is rejected rather than displayed.

## Human burden reduction

Katie can use one view to see:

- what actually completed;
- what needs attention;
- the smallest pending approvals;
- stale or failed workers;
- evidence/artifact locations;
- cost totals.

This avoids opening separate chats and manually reconciling conflicting status
claims.

## Verification

```bash
python -m unittest discover -s tests -p 'test_dashboard_snapshot.py'
python scripts/verify_webui_control.py
```

## Deployment boundary

The snapshot builder is additive and read-only. It does not start a web server,
create a schedule, call a model, publish content or contact a broker. UI wiring
requires a separately reviewed deployment with the existing backup and rollback
controls.

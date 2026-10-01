# Credit and Cost Control Contract

## Purpose

Measure useful model throughput across the four workspaces without authorising
spend or confusing credits, tokens and currencies.

The monthly 2–4B-credit figure is treated as a capacity-planning range, not a
command to consume credits and not a financial budget.

## Recorded event

Each model usage event records references only:

- event and automation-run IDs;
- workspace and timestamp;
- provider reference and logical model role;
- server-side model binding reference;
- non-reversible input fingerprint;
- cache-hit status;
- input, output, cache-read and total credit units;
- optional cost in its original GBP or USD currency.

Prompts, responses, credentials and API keys are prohibited.

## Controls

- completed model runs without a usage event are reported;
- repeated uncached fingerprints are flagged as duplicated work;
- cache use is visible;
- usage is aggregated by workspace and model role;
- GBP and USD remain separate;
- currency conversion is disabled;
- automatic provider upgrades and spend increases are disabled;
- changing budgets, plans, capacity or hard limits requires human approval.

## Capacity status

The report labels measured monthly credits as:

- `NO_DATA`;
- `BELOW_PLANNED_RANGE`;
- `WITHIN_PLANNED_RANGE`;
- `ABOVE_PLANNED_RANGE`.

These are observability labels only. They do not throttle, purchase or increase
usage.

## Human burden reduction

Katie should not have to reconcile provider totals manually. Once usage events
are connected, the dashboard can show the totals, missing metering and uncached
duplicate work automatically. Only genuine commercial decisions—provider-plan
or budget changes—remain human approvals.

Never paste provider keys, invoices containing sensitive account details, or
environment files into chat or GitHub.

## Verification

```bash
python -m unittest discover -s tests -p 'test_credit_control.py'
python scripts/verify_webui_control.py
```

## Deployment boundary

This component is read-only and additive. It creates no provider account,
changes no plan, spends no money and starts no schedule. Rollback is disabling
usage-event ingestion while preserving existing metering records as audit
evidence.

---
name: shared-portfolio-ledger
description: Single authoritative portfolio/risk ledger shared by UK and US controllers. Broker truth overrides internal state; one shared cash/risk/positions pool.
---

# Shared Portfolio Ledger

Trading 212 DEMO broker state is authoritative for equity, cash, positions, orders and fills. The internal ledger is a mirror, never the authority.

Track equity, available cash, pending commitments, positions, realised/unrealised result, planned risk, aggregate risk, daily/weekly loss, high-water drawdown, candidate reservations, exits and the 20-trade validation log.

On startup/restart reconcile from T212 before any new order. Subtract pending commitments/reservations before sizing. Legacy positions do not authorise equivalent new sizing. Verify every broker write. Prefer consolidated reconciliation and avoid bursty calls.

Risk limits are sourced from webui-control/t212-risk-controls.json and must be applied deterministically. LIVE remains disabled.

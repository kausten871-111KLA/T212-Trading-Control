# Evidence delta — broker-backed candidate readiness (2026-10-02 04:15 UK)

## Scope and status

- Register scope: **T05–T11 / D01–D07 — readiness and broker-readback subset**.
- State: **STAGED on branch; not deployed**.
- Tested implementation commit: `4306052ead5b8e06a6ff397b7c1c47f79534e263`.
- No server, WebUI, schedule, broker, account or order state was changed.

## Implemented

1. Added `worker/run_candidate_readiness.py` after the catalyst consumer in the staged systemd chain.
2. Completed catalyst reviews are rechecked deterministically for scanner state, exact T212 ticker, tradability, spread, catalyst state, disposition and source.
3. The broker is not called when no candidate survives those gates.
4. When a candidate survives, the worker performs one logical read-only `trading_dashboard` call and normalizes DEMO account, GBP equity/cash, positions and pending orders.
5. Unsafe, incomplete, non-JSON, LIVE-enabled or unavailable broker responses block readiness without an order attempt.
6. Passing produces only `READY_FOR_PROPOSAL`; deterministic risk remains `PENDING_IMMUTABLE_PROPOSAL`.
7. The risk gate now rejects missing broker timestamps, broker snapshots older than 120 seconds, non-DEMO evidence and LIVE-enabled evidence.
8. Queue completed-review access is bounded and newest-first.
9. Release manifest advanced to staged v0.10 and the readiness contract was updated.

## Verification

- GitHub Actions run 79: **SUCCESS** — https://github.com/kausten871-111KLA/T212-Trading-Control/actions/runs/36959522241
- Python compilation: passed.
- Complete unit suite: **135 passed**.
- New tests prove no broker call without an eligible candidate, exactly one broker read for an eligible candidate, explicit pending-proposal state, catalyst rejection before broker access, LIVE/incomplete broker rejection, broker failure blocking, and stale/unsafe broker-state rejection in the deterministic risk gate.
- Control-plane preflight, workspace contract, isolation audit, register builders, empty DEMO programme validation and tracked-dotenv check passed.
- CI retained `live_trading_enabled=false` and `orders_submitted=0`.

## What this does not prove

- No runtime broker connection or account fact was queried in this run.
- No current price, equity, position, order or fill is claimed.
- The staged v0.3 gateway is not deployed.
- No immutable trade proposal was produced or risk-gated.
- No human approval or DEMO order action occurred.
- Restart/persistence and Friday live-session freshness remain unverified.

## Next single item

Reconcile the methodology/agent bindings and extend the durable trading dashboard with candidate funnel, broker freshness, readiness and rejection/failure evidence.

# Evidence delta — live discovery snapshot freshness (2026-10-02 03:00 UK)

## Scope and classification

- Register IDs: **T05, T06, T07, D01**.
- State: **STAGED on branch**, not deployed.
- Branch: `feature/t212-instrument-cache-v03`.
- Implementation commit: `dc89e544adc42429aedcb8e649927597cde9245d`.
- Test-correction commit: `56867e27e3c815fa54e20dc87f2ac0604d810b1e`.
- No server, container, broker, schedule, order, or account state was changed.

## Implemented

1. Added `worker/produce_market_snapshot.py` as the no-order producer that runs before discovery.
2. It applies the deterministic Europe/London session gate before importing or calling the provider gateway.
3. It requests market clock, a broad candidate scan, and daily bars; it writes provider/feed/clock/error evidence into the snapshot.
4. Quote/trade timestamps are checked row by row. Rows older than the configured limit are excluded; an all-stale result fails closed.
5. Completed daily bars supply a 20-session volume baseline. If bars are unavailable, the snapshot records the explicit `previous_session_fallback` method rather than implying relative volume is complete.
6. `worker/discovery_adapter.py` now rejects fixture-labelled, non-live-provider, unenforced, or stale-row snapshots in the runtime path. Fixtures remain available only through an explicit test opt-in.
7. `deploy/systemd/t212-discovery.service` stages the producer as `ExecStartPre` and reads the optional root-controlled `/etc/t212-scanner/runtime.env`.
8. `market_data_gateway.py` now carries `previousVolume` through candidate rows.
9. Release manifest and source-priority/readiness documents were updated.

## Verification

- GitHub Actions run 76: **SUCCESS** — https://github.com/kausten871-111KLA/T212-Trading-Control/actions/runs/36954189613
- Python compilation: passed.
- Complete unit suite: **121 passed**.
- Control-plane preflight, workspace contract, workspace-isolation audit, implementation/gap registers, empty DEMO programme validation, and tracked-dotenv check: passed.
- New tests cover: broad snapshot output, stale-row exclusion, 20-day baseline, explicit bars fallback, all-stale failure, runtime fixture rejection, test-only fixture opt-in, and stale-row rejection even when the file itself is recent.
- CI evidence retained `live_trading_enabled=false` and `orders_submitted=0`.
- Initial run 75 failed only on a stale expected test label; commit `56867e27...` corrected the assertion and run 76 passed.

## What this does not prove

- No runtime checkout or OpenWebUI container was reachable, so deployment and persistence are unverified.
- No fresh live-market snapshot was collected in this run.
- Closed-market fixtures prove transformation and gates only; they are not fresh market evidence.
- The catalyst queue still needs a verified downstream consumer.
- This does not prove broker readback, feed entitlement, or Friday pre-open readiness.

## Minimal activation boundary

Required human-only authority is limited to server access and any provider credentials already approved:

1. On the Contabo server, place approved Alpaca values only in root-controlled `/etc/t212-scanner/runtime.env`; never paste tokens into chat, GitHub, commands recorded in history, or WebUI prompts.
2. Deploy the reviewed branch through the existing backup/install runbook, then run the producer once in no-order mode and inspect `market_snapshot.json`.
3. Accept only if source is live-provider, fixture is false, row freshness is enforced, at least one row is within the freshness limit, and the cycle reports `orders_submitted=0`.
4. Roll back using the existing timestamped source backup if any acceptance check fails.

## Next single item

Implement and test the missing structured catalyst-queue consumer, with claim/ack/retry semantics and no broker-write authority.

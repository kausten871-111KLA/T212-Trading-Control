# Evidence delta — structured catalyst queue consumer (2026-10-02 04:00 UK)

## Scope and status

- Register scope: **T05–T11 / D01–D07 — catalyst-consumer subset**.
- State: **STAGED on branch; not deployed**.
- Branch: `feature/t212-instrument-cache-v03`.
- Implementation commit: `51796d4c64e11da622259147f3958d9b7f964bfc`.
- Compatibility correction: `e7f7d418d8add0542fd53df3eb635dfd8491932d`.
- No server, OpenWebUI, schedule, broker, account or order state was changed.

## Implemented

1. Added `worker/run_catalyst_consumer.py`, a bounded consumer for deterministic scanner candidates.
2. The session gate executes before reviewer configuration or provider calls.
3. Each invocation processes at most five events; the daily queue limit remains twenty.
4. Queue claims now carry expiry leases. Expired claims can be recovered after a crash without double-processing active claims.
5. Failed reviews return to pending until a maximum of three attempts, then remain visibly failed.
6. Reviewer output is rejected unless it matches the required JSON schema, candidate symbol, catalyst/disposition enums, source rule and confidence range.
7. Completed reviews are acknowledged in the durable queue and appended to a private review ledger.
8. The staged systemd service runs the consumer after discovery. Missing endpoint/model/token records a blocked status without discarding queued candidates.
9. The consumer contains no Trading 212 hostname, broker import, order submit, close-position or account-mutation path.
10. Release manifest advanced to staged v0.9 and the catalyst handoff contract now records the consumer/configuration boundary.

## Verification

- GitHub Actions run 78: **SUCCESS** — https://github.com/kausten871-111KLA/T212-Trading-Control/actions/runs/36959013678
- Python compilation: passed.
- Complete unit suite: **129 passed**.
- New acceptance cases cover successful claim/validation/acknowledgement, five-item bound, daily budget, deduplication, retry then terminal failure, expired-claim recovery, active-claim exclusion, symbol mismatch and unsourced claimed catalyst rejection.
- Control-plane preflight, workspace contract, isolation audit, register builders, empty DEMO programme validation and tracked-dotenv check all passed.
- CI retained `live_trading_enabled=false` and `orders_submitted=0`.
- The first CI run exposed a backward-compatibility break in the legacy acknowledgement call; `e7f7d418...` restored that interface and the complete suite then passed.

## Runtime boundary

This proves branch logic only. It does **not** prove:
- the OpenWebUI/DeepSeek endpoint is configured or reachable;
- the reviewer has working web-search/source access;
- a real candidate has been reviewed;
- deployment, persistence, restart behaviour or live market freshness;
- broker readback or Friday DEMO session readiness.

Required secret-bearing values belong only in root-controlled `/etc/t212-scanner/runtime.env`: `T212_CATALYST_REVIEW_URL`, `T212_CATALYST_REVIEW_TOKEN`, and `WEBUI_MODEL_DEEP_REASONING`. Never paste their values into chat, GitHub or WebUI prompts.

## Next single item

Close the next discovery-chain gap by wiring validated catalyst results into deterministic risk/readiness and broker-readback evidence, without adding autonomous order authority.

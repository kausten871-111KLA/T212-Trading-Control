# Morning handoff — WebUI / T212 control lane (2 October 2026)

## Executive decision

- **Friday unattended T212 DEMO execution: NO-GO at handoff.**
- **Friday read-only pre-open assurance: READY TO RUN.**
- No current server, market, broker, scheduler or explicit session-authority evidence was available to satisfy the 18-check gate.
- Repository implementation is **STAGED**, not deployed. No provider/model/broker/order action occurred in this control lane.

## Completed and evidenced

| Register scope | State | Evidence |
|---|---|---|
| T12 / A06 / S08 scheduling and cost control | STAGED | Deterministic 14:20–21:05 Europe/London weekday gate before provider/model work; lock, deduplication and bounded retry; 107 tests |
| T01–T04 / T07 / A07 cache-first gateway | STAGED | Shared-cache/lock contract, bounded GET retry, no POST retry, stale fallback, ten lookup acceptance; CI run 74 |
| T05–T11 / D01–D07 discovery chain | STAGED | Freshness-enforced snapshot, volume baseline/fallback, catalyst consumer, deterministic readiness and read-only broker normalization; CI runs 76, 78 and 79 |
| M01–M12 / A01–A09 methodology/dashboard | STAGED | Four non-persistent/no-broker-write role bindings; fail-closed evidence dashboard and file handoff; CI runs 80 and 81 |
| T01–T12 / D01–D07 / M01–M12 / A01–A09 pre-open gate | STAGED | 18 PASS/FAIL/MISSING dependencies; GO only with zero FAIL/MISSING; CI run 82 |
| F01–F05 one-command assurance | STAGED | Runtime inventory → dashboard → gate under one lock; read-only/no-order; commit `52f0bfbede1c2aac8cf0c9c4b4bdb5997348f690`; CI run 83, 151 tests |
| Apps / Plugins / Bots | BLOCKED_RUNTIME | Isolation/registry checks pass in CI; relay/runtime bindings have no WebUI acknowledgement or runtime proof |
| You Heal / Books | STAGED_CONFIG_ONLY | Existing governance/pipeline assets preserved and isolation audit passed; no content produced or published |
| WebUI core capabilities / upgrade | DEFERRED | Vision/search/STT/TTS/images/batch not end-to-end proven; v0.11.4 upgrade correctly deferred |

## Test summary

- Latest exact-commit CI: https://github.com/kausten871-111KLA/T212-Trading-Control/actions/runs/36976943139
- Complete suite: **151 passed**
- Python compilation, control-plane preflight, workspace contract, isolation audit, register builders and dotenv audit: PASS
- CI safety: `DEMO`; `live_trading=false`; `order_mutation=false`; `orders_submitted=0`
- Empty/missing evidence behavior: `NO_GO`, never inferred ready
- Runtime deployment and persistence: **not tested**
- Current market/broker/account facts: **not collected in this lane**

## Minimal human actions

### 1. Required — run current read-only assurance on the server

On Katie's laptop, open the existing PowerShell window and SSH to the configured Contabo server. After the server prompt appears, run:

```bash
cd /home/katie/t212-scanner-test && git status --short && git fetch origin feature/t212-instrument-cache-v03 && git checkout feature/t212-instrument-cache-v03 && git pull --ff-only origin feature/t212-instrument-cache-v03 && mkdir -p /home/katie/preopen-evidence && python3 scripts/run_preopen_assurance.py --state-dir /var/lib/t212-scanner --runtime-output /home/katie/preopen-evidence/runtime.json --dashboard-output /home/katie/preopen-evidence/dashboard.json --gate-output /home/katie/preopen-evidence/gate.json --lock-file /home/katie/preopen-evidence/gate.lock
```

Expected result: one JSON line containing `decision`, counts and evidence paths. Exit code 2 / `NO_GO` is a valid diagnostic result. Stop if `git status --short` shows user changes or the pull is not fast-forward.

Never paste passwords, SSH keys, T212/Alpaca tokens, OpenWebUI admin keys, relay tokens or `runtime.env` contents into chat or GitHub.

Afterward: share only the final non-secret JSON summary. Executive Orchestra can reconcile the exact FAIL/MISSING rows and prepare the next bounded change.

### 2. Required for live WebUI coordination — activate/verify the reviewed relay

In Open WebUI, open **Open WebUI Site Configurator — DeepSeek** and use the existing relay activation instruction. Success must read: `RELAY ACTIVE / READ WORKING / WRITE WORKING` or `WRITE TOKEN REQUIRED / latest ChatGPT handoff received`.

Never paste `GITHUB_RELAY_TOKEN`; if write access needs it, place it only in the approved server-side secret location.

Afterward: Issue #5 becomes the durable coordination lane; it still has no WebUI acknowledgement at this handoff.

### 3. Conditional — session authority

Only if Katie wants order-capable unattended DEMO operation, record the exact DEMO-only authority and approval boundary in Trading Operations. Do not authorize LIVE, forced trades, weakened risk gates or an inferred blanket approval. Without explicit evidence, the gate remains NO-GO while read-only discovery can continue.

## Monday readiness gaps

1. Synchronize and back up the intended runtime separately from the test checkout; prove rollback.
2. Prove the shared host/container cache bind and deploy v0.3, not the reported live v0.2 tool.
3. Collect fresh provider snapshot, instrument baseline/diff, scanner, catalyst, liquidity/spread, broker/account and worker/timer evidence.
4. Prove one scheduler owner; prevent overlapping WebUI and systemd controllers.
5. Complete the 18-check acceptance evidence, including position lifecycle, P&L/equity curve and session authority.
6. Verify relay and actual OpenWebUI model/tool/skill bindings.
7. Keep WebUI v0.11.4 upgrade deferred until backup, rollback and acceptance gates pass.

## Remaining queue

- Interpret the first server gate result and repair only its highest blocking dependency.
- Runtime-prove Apps/Plugins/Bots bindings and relay.
- Runtime-prove You Heal/Books workspace file visibility without producing/publishing content.
- Validate optional WebUI vision/search/audio/image/batch capabilities after the T212 critical path is stable.

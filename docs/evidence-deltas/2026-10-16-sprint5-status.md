# Sprint 5 — Single-instance monitor supervisor (16 October 2026)

## Verified deliverable
A locally tested, opt-in Linux monitor loop was built on the existing PR #17 position-monitor core. It provides an exclusive OS lock (preventing a second worker), atomic private health receipts, stop requests, polling, error containment, and a last-cycle HEALTHY/DEGRADED indicator. It does not create trade decisions, new schedules or new broker connections. It cannot start automatically: it has no executable service entrypoint.

**Local test evidence:** 37/37 synthetic unit tests passed (27 previous integration tests plus 10 new supervisor tests); Python compilation checks passed. Tests used fake callbacks and temporary SQLite databases; no broker, model, network or paid services were called.

## Deployment truth
The new source and tests are included in the user-facing Sprint 5 ZIP artifact, but the GitHub source-file creation attempt was blocked by connector safety checks. Therefore this branch currently contains this evidence note only, **not** the supervisor implementation. No PR or production deployment is claimed.

## Next implementation
1. Review and upload `openwebui/tools/supervised_monitor_worker.py` and `tests/test_supervised_monitor_worker.py` from the Sprint 5 package into a reviewed branch based on PR #17.
2. Reconcile Sprint 2–4 durable queue/dispatcher/monitor bridge with DeepSeek's pending SQL/event contract. Reuse the v0.2.3 DEMO gateway as sole broker writer.
3. Bind authenticated DEMO position and intent-reconciliation callbacks. Only then create a supervised service with one process, controlled restart, health alerts, and rollback.
4. Verify restart recovery and duplicate prevention in staging. Do not duplicate OPEN/MIDDAY/CLOSE automations or touch LIVE.
5. Parallel audio P0: last verified ElevenLabs errors were 401/400; the browser playback/continuous voice tests remain open. Remote commands were blocked in this sprint, so no new server audio state was verified.

**No production changes, no broker orders, no trading-strategy restrictions, no Work-credit spend.**

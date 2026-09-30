# Persistent Trading Discovery Worker (DEMO / read-only first)

This package is designed to run independently of ChatGPT, a browser tab, or the user's laptop.

Safety baseline:
- Trading 212 DEMO only.
- Discovery, cache refresh, queueing and audit are read-only.
- No order action is implemented in the worker package.
- Broker order submission remains isolated in the existing Open WebUI T212 DEMO gateway.
- Do not enable timers until read-only tests pass on Contabo.

Services prepared:
- `t212-discovery.timer`: deterministic 5-minute worker cadence.
- `t212-cache-refresh.timer`: daily instrument-master refresh.
- `t212-eod-audit.timer`: post-US-close missed-green audit.
- `worker/healthcheck.py`: verifies recent healthy worker status.

Deployment target:
`/home/katie/t212-scanner`

State target:
`/var/lib/t212-scanner`

Before enablement:
1. Back up Open WebUI DB and tool export.
2. Verify DEMO credentials only.
3. Validate market-data screener availability.
4. Run one manual worker cycle.
5. Confirm orders_submitted=0.
6. Inspect logs/status.
7. Only then enable timers.

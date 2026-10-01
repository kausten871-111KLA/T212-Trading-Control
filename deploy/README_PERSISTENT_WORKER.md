# Persistent Trading Discovery Worker (DEMO / DEMO-only first)

This package is designed to run independently of ChatGPT, a browser tab, or the user's laptop.

Safety baseline:
- Trading 212 DEMO only.
- Discovery, cache refresh, queueing and audit are DEMO-only.
- DEMO execution is permitted only through the approved Trading 212 DEMO gateway; LIVE remains disabled.
- Broker order submission remains isolated in the existing Open WebUI T212 DEMO gateway.
- Do not enable timers until DEMO-only tests pass on Contabo.

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

## Timer reliability controls

- Cache refresh is pinned to `07:15 Europe/London`; it no longer inherits an unknown host timezone.
- The EOD audit remains pinned to `21:20 Europe/London`.
- The five-minute discovery cadence is timezone-independent.
- Each oneshot worker has a bounded timeout, three-attempt start limit, failure retry, private temporary directory, restrictive umask and read-only system/home views.
- Only `/var/lib/t212-scanner` is writable by these services.

Before copying or enabling units, validate them without changing system state:

```bash
systemd-analyze verify deploy/systemd/*.service deploy/systemd/*.timer
```

After installation but before enablement, inspect the calculated schedule:

```bash
systemctl list-timers 't212-*' --all
```

Success means the cache refresh and EOD audit show UK-local wall-clock times, discovery shows a five-minute cadence, and no unit is enabled until the manual DEMO-only smoke test has passed. Unit installation and enablement remain separate, explicitly approved actions.

# Reconnection Handoff — 30 Sep 2026

## Current validated state
- T212 DEMO instrument endpoint works.
- Self-contained Gateway v0.3 candidate passed container validation.
- Instrument master size observed: 18,475.
- Unit suite passed 9/9 before the later tier-boundary test addition.
- Alpaca credentials, clock, movers, most-active, snapshots and bars all reported available.
- Trading remains DEMO-only; LIVE remains disabled.

## Important discovery correction
Alpaca documents that the stock movers endpoint resets at the regular-market open. Before 09:30 ET it intentionally shows the prior market day's movers. Therefore the 29 Sep timestamp observed before the 30 Sep regular open was expected pre-open behaviour, not by itself an outage.

## Required session logic
- Before 09:30 ET: screeners are seed lists; current snapshots/quotes determine current state.
- 09:30-16:00 ET: current-session movers + most-active are the broad discovery source, with candidate re-pricing from current snapshots.
- After close: screeners represent the completed session and support EOD audit.
- 20-day completed daily bars supply the average-volume baseline.
- T212 tradability comes from the cached instrument master.
- Tier ladder uses floor thresholds [5,10,20,50,100]; +81.5% is tier 50.

## First actions when laptop access returns
1. Pull branch and rerun syntax/unit tests including tier boundaries.
2. Back up live Open WebUI SQLite DB using an online SQLite backup.
3. Export current T212 DEMO gateway source.
4. Install Gateway v0.3 candidate only after backup.
5. Smoke-test cache status, symbol lookup, new-on-T212, dashboard, positions and orders.
6. Confirm DEMO-only / LIVE-disabled state.
7. Wire and manually test persistent worker/timers before enabling.
8. Verify tomorrow's US-open and US-close automations and destination/workspace.
9. Issue one canonical update to all relevant WebUI chats.
10. Remove/rotate the temporary Open WebUI admin API key after configuration work.

## WebUI canonical status message
30 SEP SYSTEM UPDATE: Contabo-hosted Open WebUI is stable behind Cloudflare Access. T212 is DEMO-only and LIVE remains disabled. Gateway v0.3 has passed isolated container validation and adds a persistent instrument cache so broker metadata is not repeatedly requested per symbol. Alpaca mover, most-active, snapshots and bars are available. Discovery logic is session-aware: prior-session mover results before 09:30 ET are expected and used only as seeds; after market open, current-session screeners plus current snapshots drive discovery. Deterministic gates, movement tiers, catalyst queue controls, persistent ledger and missed-green audit are staged. Next controlled changes are Gateway v0.3 installation, 20-day volume baseline join, persistent worker/timer enablement and tomorrow's DEMO trading-window verification.

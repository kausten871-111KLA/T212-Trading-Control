# Live Discovery Source Priority

For market-hours discovery, data freshness takes precedence over convenience.

US market-hours source order:
1. Live/current SIP or delayed-SIP symbol scan/snapshots with current timestamps.
2. Current-session broad mover / most-active feeds only when their `last_updated` timestamp is for the active session.
3. Previous-session mover/most-active feeds may seed symbols only; they must never be treated as current mover truth.

Rules:
- Reject a discovery feed as stale when its update date is not the active US trading date.
- Re-price every shortlisted symbol from a current quote/snapshot before any decision.
- Calculate dollar volume from current-session price × current-session day volume.
- Join historical daily bars for the 20-day volume baseline.
- Movement tiers are floor thresholds: [5,10,20,50,100]. Example: +81.5% => tier 50; +100% => tier 100.
- T212 tradability must come from the cached instrument master, not one API metadata request per symbol.
- Catalyst research occurs only after deterministic qualification / escalation to control token and search cost.

This policy is discovery/qualification logic and does not enable LIVE Trading 212 execution.

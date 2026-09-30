# Market Data Discovery Readiness Gate

The 5-minute worker must remain unarmed until the discovery source is proven.

Required live checks:
- Alpaca credentials loaded.
- Market clock available.
- Top movers endpoint available OR a replacement discovery feed is selected.
- Most-active endpoint available OR a replacement discovery feed is selected.
- Snapshot endpoint works for a supplied symbol batch.
- Historical daily bars work for 20-day volume baselines.
- Quote timestamps are current.
- Any execution path must use the approved Trading 212 DEMO gateway; LIVE execution must remain unavailable.

If Alpaca screeners are plan-restricted, do not fake broad discovery with a tiny static watchlist. Select one market-data source capable of broad US movers, then separately add UK/LSE coverage.


## Session-aware screener freshness

Alpaca's stock movers endpoint is expected to show the previous market day's movers before the 09:30 ET regular-market reset. Do not classify that pre-open state as an outage. The worker must:
- inspect the Alpaca market clock;
- treat pre-open screeners as seed lists only;
- require current snapshots/quotes for pre-market qualification;
- require current-session screeners after the market opens;
- alert only when a screener remains on the prior session after the regular-market reset grace period.

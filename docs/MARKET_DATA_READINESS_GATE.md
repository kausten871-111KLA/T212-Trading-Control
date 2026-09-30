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
- No broker order function is callable from the discovery worker.

If Alpaca screeners are plan-restricted, do not fake broad discovery with a tiny static watchlist. Select one market-data source capable of broad US movers, then separately add UK/LSE coverage.

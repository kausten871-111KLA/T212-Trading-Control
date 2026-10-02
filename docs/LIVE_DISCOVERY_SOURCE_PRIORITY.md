# US Discovery Source Priority and Session Freshness

Alpaca documents that the stock movers endpoint resets at the regular market open. Before that reset it intentionally shows the previous market day's movers. Therefore a previous-session `last_updated` before 09:30 ET is expected behaviour, not an API fault.

## Source rules

1. During regular US market hours (09:30-16:00 ET), use current-session mover + most-active screeners as broad symbol discovery, then re-price every candidate from a current SIP/delayed-SIP snapshot.
2. Before 09:30 ET, previous-session screener results are seed symbols only. Pre-market decisions must use current pre-market snapshots/quotes and must not label the previous-session screener as current-session mover truth.
3. After the regular session, screener results describe the completed session and can drive EOD audit.

## Qualification rules

- Re-price every candidate from a current quote/snapshot before qualification.
- Reject quote/snapshot timestamps that are outside the intended session window.
- Join historical completed daily bars to build a 20-day average-volume baseline.
- When the regular session is open, relative-volume pace may use elapsed-session fraction against the historical daily-volume baseline.
- Dollar volume = current-session day volume × current price.
- T212 tradability must come from the cached T212 instrument master; do not request the full broker instrument list once per symbol.
- Movement tiers are floor thresholds [5,10,20,50,100]. Example: +81.5% => tier 50; +100% => tier 100.
- Catalyst research starts only after deterministic qualification or a new movement-tier escalation.

## Safety / execution boundary

This document controls discovery freshness and qualification. Trading 212 remains DEMO-only; LIVE stays disabled.


## Implemented branch-side producer contract

The staged host worker now has an explicit read-only producer at
`worker/produce_market_snapshot.py`. The systemd discovery service runs it as
`ExecStartPre`, inside the same deterministic session window, before the
scanner reads `market_snapshot.json`.

The producer:

- obtains the Alpaca market clock;
- combines broad movers and most-active discovery through `candidate_scan`;
- captures quote/trade/day/previous-day snapshot fields;
- calculates a completed-20-day volume baseline where daily bars are available;
- labels the explicit previous-session-volume fallback when bars are unavailable;
- rejects missing or stale quote/trade observations before writing;
- records provider/feed, screener errors, clock state and freshness evidence;
- has no T212 or Alpaca order endpoint and reports `orders_submitted=0`.

This is **STAGED**, not proof that host Alpaca credentials or a live producer run
exist. The service references only the root-controlled path
`/etc/t212-scanner/runtime.env`; secret values must never be committed or
pasted into chat.

# Market Data Activation & Read-Only Smoke Test

## Purpose
Activate the read-only Alpaca Market Data Gateway inside the local Open WebUI Trading Operations model without exposing credentials or placing a trade.

## Safety boundary
- Trading 212 remains DEMO only.
- Alpaca is market-data only.
- Do not paste Alpaca or T212 credentials into chat.
- Do not place an order during this smoke test.
- Broker execution remains exclusively through the T212 DEMO Gateway.

## Human activation
From the PowerShell session used to run Open WebUI:

1. Stop Open WebUI with Ctrl+C.
2. Ensure the existing T212 DEMO and Open WebUI admin environment variables are still loaded.
3. Run the repository helper:
   `& .\scripts\start_openwebui_with_alpaca.ps1`
4. Enter Alpaca API key and secret into the hidden local prompts.
5. Leave the PowerShell window open.

If using another working directory, run the script by its full local path.

## Read-only acceptance sequence
Use a fresh **Trading Operations — DeepSeek** chat.

### Test 0 — gateway health check
Ask:
> Use the Market Data Gateway health_check with screener probing enabled. Do not trade. Report whether credentials are loaded, whether the market clock works, and whether movers/most-active access is available or plan-blocked.

PASS:
- credentials are recognised;
- market clock authenticates;
- any screener limitation is reported explicitly rather than treated as total gateway failure.


### Test 1 — market clock
Ask:
> Use the Market Data Gateway only. Read the US market clock. Do not trade. Report provider, market open/closed state, timestamp, and any API error.

PASS:
- tool is invoked;
- authenticated response received;
- no broker action.

### Test 2 — movers
Ask:
> Use Market Data Gateway top_movers only. Return the current top 10 gainers and top 10 losers. Do not trade. If the endpoint is forbidden by my Alpaca plan, report the exact error and stop.

PASS:
- movers returned; or
- exact subscription/403 blocker reported without guessing.

### Test 3 — most active
Ask:
> Use Market Data Gateway most_active with top 20 by volume. Read-only. Do not trade.

### Test 4 — candidate scan
Ask:
> Run candidate_scan top 20 using the Market Data Gateway. Do not execute. Return only symbols, price, change versus previous close, volume, bid/ask spread percentage where available, and any source errors.

PASS:
- a candidate set is generated; or exact source/plan errors are surfaced.

### Test 4B — delayed consolidated fallback
If the real-time SIP screener is plan-blocked, ask:
> Use scan_symbols with feed delayed_sip on this supplied candidate/watchlist universe. Rank the top gainers and losers. Do not trade.

PASS:
- the supplied universe is ranked using delayed consolidated data; or
- the exact feed/subscription error is returned.

This fallback does not replace a broad-market discovery source; it proves the qualification data path still works when Alpaca's real-time SIP screener is unavailable.

### Test 5 — qualification handoff
Ask:
> From the candidate scan, select up to 5 candidates for INVESTIGATOR review. Apply the canonical Trading Operations gates. No execution. Label each gate CONFIRMED / PROBABLE / UNKNOWN / PASS / FAIL as appropriate, and identify what additional evidence is required before a trade decision.

PASS:
- no candidate silently progresses to execution;
- unknown evidence remains explicit.

### Test 6 — broker/read-only dashboard
Ask:
> Use the T212 DEMO Gateway only. Run operations_dashboard with history_limit 20. Do not place, modify, cancel or close orders. Report broker-verified account, open positions, pending orders, recent order history and recent transactions.

PASS:
- broker state is returned;
- `liveTradingEnabled` remains false;
- no write occurs.

## Definition of ready for first integrated DEMO loop
All of the following:
- Market Data Gateway authenticates.
- At least one discovery path works.
- Snapshot/quote data can be obtained for candidates.
- T212 operations dashboard works.
- Canonical knowledge and five Trading Skills remain attached.
- No LIVE capability is enabled.
- No broker write occurs during smoke testing.

Only after these pass should the system run:
SCAN -> EXPLAIN -> QUALIFY -> DECIDE -> EXECUTE -> VERIFY -> MONITOR -> EXIT -> AUDIT -> LEARN.

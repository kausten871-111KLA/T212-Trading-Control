# Friday 23 October 2026 — DEMO winners discovery, production read-only audit

## Verified by connected WebUI database (not model self-report)
Inspected the running Open WebUI SQLite database in read-only mode on Contabo after Desktop Commander reconnected. No credentials or private trading token copied. No SQLite mutation, model-setting change, broker order, or automation change made by this audit.

Model trading-operations--deepseek:
- Web Search capability true; model defaultFeatureIds includes web_search
- builtinTools.automations true
- Five intact custom tool IDs: trading_212_demo_gateway_tool, market_data_gateway, contabo_command_bridge, trading_brain_research_context, twelve_data_global_research
- All five existing automations active; Friday 23 Oct Research, Controller, OPEN and MIDDAY show successful automation_run records with chat IDs.

### 13:00 UK — Morning Research Runner, actual scheduled execution
- WebUI chat created at 12:00:06 UTC; run marked success.
- Tool calls include read_memory_path, market_clock, top_movers, most_active, candidate_scan, fetch_url, search_web, snapshots, latest_quotes and write_note.
- top_movers last_updated = 2026-10-22T23:59:00Z; 20 names; none of target US winners.
- most_active last_updated = 2026-10-22T23:59:00Z; 30 names; none of target US winners.
- candidate_scan = 30 names, none of target US winners. Previous-day ranking may be normal before the US open; it cannot substitute for premarket discovery.
- The actual Research Runner automation prompt explicitly instructs retrieval of the US StockAnalysis gainers and active pages, followed by Yahoo UK; however the only observed fetch_url call was for https://uk.finance.yahoo.com/markets/stocks/gainers/ . No StockAnalysis retrieval call was recorded.
- Yahoo fetched page contained a visible "Something went wrong" header but also some market-gainer rows including ORCP.L; output quality and extraction acceptance need validation instead of treating HTTP success as clean data.
- This establishes that model Web Search works in a scheduled automation, but its source coverage and enforced fetch steps are insufficient.

### 14:35 UK — US OPEN, actual scheduled execution
- OPEN used market clock, top_movers, most_active, candidate_scan and snapshots, among other existing broker tools. It did discover RHI: Robert Half, approximately +17.7–18.1% against prior close at ~09:35 ET.
- Saved 2026-10-23T13:35:46Z IEX snapshot: RHI trade ~$44.49, bid $41.32, ask $46.20, displayed spreadPct 11.15%. Follow-up IEX snapshot ~13:36:41Z still indicated spreadPct 10.85%. DeepSeek rejected RHI as wide-spread/illiquid. This was **discovered then rejected**, not globally invisible.
- Critical caveat: IEX-specific quotes can be far wider than consolidated NBBO; no SIP/NBBO snapshot or T212 executable bid/ask at exactly 09:35 ET has yet been verified. Do not call this definitely a mistaken rejection or claim the stock was tradeable at a later 1.1% quote. Require quote venue, timestamp, sizes, age, and consolidated-crosscheck before a firm conclusion.

### 17:30 UK — US MIDDAY, actual scheduled execution
- candidate_scan returned 30 names including BOLT, CLRO, MYND, GPUS, BKYI.
- top_movers returned those same five and most_active contained MYND, GPUS and LUCD.
- BKYI was individually investigated at ~$3.62, up ~32.7% vs prior close, IEX spread ~0.83%; the model rejected entry due to retreat from the observed 15:50 UTC high $3.91. This is **discovered late / post-peak**; its early intraday rise was not captured by scheduled Research Runner.
- BOLT, CLRO, MYND and GPUS appeared in the midday screener but were labelled too wide-spread or very low-price. These were not wholly missing from Alpaca.
- RHI and NAUT were absent from the latest MIDDAY candidate_scan list. NAUT did not appear in the sampled morning scan either; further historical scan evidence needed.

### Independent historical 5-minute IEX bars
Alpaca five-minute US-stock bars on Friday 23 Oct:
- NAUT: 09:30 ET opening price $2.59; 09:40 bar closes $2.77 (>5% above open), 10:00 bar $2.88 (>10%), 10:20 bar $3.00 (>15%); observed high $3.25 at 10:55 ET.
- RHI: 09:30 ET opening price $42.32; observed high $46.27 at 12:15 ET.
- BKYI: 09:30 ET opening price $3.26; the opening bar closes $3.66 (>10%); observed intraday high $3.91 at 11:50 ET.
These are hindsight IEX bars, not real-time scan signals or verifiable broker fill prices. No real-execution profit estimate is justified.

### Additional source and identity evidence
- Direct Alpaca asset API identified BOLT, CLRO, BKYI and LUCD as NASDAQ common stocks; RHI as NYSE Robert Half; NAUT as NASDAQ Nautilus Biotechnology (NOT Nauticus Robotics).
- GraniteShares official website confirms 3SRR is the 3x inverse Rolls-Royce ETP, not an equity: https://graniteshares.com/uk/etps/3x-short-graniteshares-rolls-royce/
- Euronext official 23 Oct Brussels news feed lists Belysse Group's Q3 2026 Trading Update at 07:15 CEST (06:15 UK), before the Research Runner: https://live.euronext.com/en/markets/brussels
- Remaining EU tickers, particularly TCID, need exact ticker, ISIN, currency and listing classification.
- StockAnalysis conditions automated AI-crawler access on robots.txt compliance (with restrictions on bulk extraction/competing databases): https://stockanalysis.com/terms-of-use/ . Yahoo prohibits automated collection without express permission: https://legal.yahoo.com/in/en/yahoo/terms/otos/index.html . No broad permission is inferred from successful fetch_url.

## Engineering implications — preserve current DEMO trading setup
1. **Implement source acceptance receipts** for the existing Research Runner: source URL/authority, retrieved timestamp, count of rows extracted, freshness/asof, venue, and a pass/fail/no-data reason. A prompt mentioning a source does not prove the tool invoked it. Test this using existing automation's saved run chats, not another scheduled bot.
2. **Address premarket and post-open discoverability.** The 13:00 UK runner ran at 08:00 ET and queried previous-day movers, which cannot find an emerging 09:40 ET NAUT move; the 09:35 ET US OPEN broad screen must be able to dynamically discover, filter and reassess new movers rather than remain locked to stale premarket playbooks. Current next scheduled broad rescan at 12:30 ET is too late for many early moves.
3. **Keep discovery and trade eligibility distinct.** Preserve candidates even if sub-$2, warrants or leveraged products appear; classify instrument type and reason not selected in an auditable ledger. The user explicitly does not want assistant-invented strategy restrictions in DEMO. The broker execution engine can still use verified T212 availability and observed bid/ask conditions when deciding.
4. **Quote reliability and timing.** IEX-only snapshots are not necessarily SIP/NBBO or T212 dealing quotes. Store provider/venue/quote timestamp/spread/size and seek better verification before excluding a promising name on a single IEX spread snapshot.
5. **Catalyst alerts for UK/EU.** Corporate disclosures can publish early (Belysse at 06:15 UK), so a US-focused 13:00 UK runner is not sufficient for European pre-open news. Integrate a lawful, permitted disclosure/feed path through existing supervised architecture; do not create duplicate trading services/automations.
6. **Evidence-only audit module:** runtime/deepseek/discovery_evidence_audit.py committed to existing draft PR #21, plus tests/test_discovery_evidence_audit.py (6/6 passed in isolated Contabo checkout). It distinguishes first ingested ticker, first runner candidate, first decision and actual DEMO receipt, with explicit event times, and never infers missing logs equal a missed trade.
7. **Next acceptance:** compare actual saved morning/open/midday tool outputs for all 15 screenshots, validate provenance/quote quality, record genuine first discovery time, and join any executed DEMO orders only after a fresh authenticated T212 gateway history read. No made-up FinMem outcome.
8. **Pending separate DST task:** five existing WebUI clocks for Oct 26–30 need a supported authenticated reversible schedule update; not done during this audit. Restore on Nov 2. Keep LIVE disabled.

## Proof boundary
This audit confirms **already operating scheduled browser fetch and broker-candidate research**, not that a separate model-background queue/worker was deployed. The newer autonomous background queue and host bridge remain staged in draft PR #21, pending production integration.
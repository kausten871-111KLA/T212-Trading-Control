# HANDOFF.md — Autonomous Runtime Deployment Instructions

**Author:** DeepSeek Trading Operations (controller). **Deploy by:** OpenAI engineering.
**Constraint:** Do NOT redesign architecture or change trading methodology. DEMO only, LIVE disabled, single gateway.

## Files in this package
- `schema.sql` — complete SQLite DB (deploy first). The original handoff calls it 17 tables; actual supplied schema has 20 application tables.
- `orchestrator.py` — deterministic worker. Only the two SEAMs (GatewayAdapter, DataSource) need wiring.
- `HANDOFF.md` — this file.

## Dependencies
- Python 3.9+ (stdlib: sqlite3, threading, json, logging, time, dataclasses).
- `apscheduler` (OPTIONAL — graceful degradation if absent; needed for cron phase triggers).

## Deployment steps
1. Create a directory, place all files.
2. `python -c "import orchestrator; db=orchestrator.StateDB(); db.init_schema()"` to build the DB.
3. Implement `GatewayAdapter` against the live T212 v0.2.3 tool (17 methods; preserve durable intent IDs, read-back verification, no-blind-retry).
4. Implement `DataSource` against Alpaca (existing) + Twelve Data / Alpha Vantage (pending).
5. Run a DRY RUN: no `TRADE AUTHORISED` token; verify events flow pending→claimed→done; no real orders.

## Integration points (T212 gateway v0.2.3)
- Tool id: `trading_212_demo_gateway_tool` (preserved, not duplicated).
- 17 callable methods: trading_dashboard, find_instrument, recent_order_history, recent_transactions, operations_dashboard, list_positions, list_orders, size_quantity, place_market_order, close_position, place_stop_order, place_limit_order, place_stop_limit_order, cancel_order, reconcile_order_intent, place_market_order_with_intent, close_position_with_intent.
- GatewayAdapter maps to: dashboard→trading_dashboard; place_market→place_market_order_with_intent; place_limit→place_limit_order; place_stop→place_stop_order; cancel→cancel_order; list_orders→list_orders; list_positions→list_positions; reconcile→reconcile_order_intent.
- NOTE: dashboard still reports version "0.2.1-cache-candidate" (cosmetic lag); actual code path is 0.2.3.

## Alpaca data source
- Already configured server-side, READ-ONLY, credentialsLoaded:true (health_check confirms).
- Free tier = IEX single-venue (live quotes/snapshots/bars/movers/actives/clock) + delayed_sip.
- No credentials required in this package — reuse existing server-side config. Do NOT hardcode keys.

## Preferred topology
- **OPTION A (recommended): Open WebUI Pipe/Function** — runs server-side inside Open WebUI, reuses the existing T212 gateway + Alpaca. Keeps single-broker-connection + credentials server-side.
- Option B (Contabo standalone worker) is acceptable but must become THE single gateway (no parallel connection).

## Known issues / unfinished code
- GatewayAdapter + DataSource are SEAMS (NotImplementedError) — engineering must implement them.
- scheduler cron hours are UTC placeholders — verify/adjust for ET market hours.
- SHA-256 integrity of gateway source UNVERIFIED (anchored to pinned commit + version + method-list).
- 429 read-path rate-limiting persists (cache is partial); request-pacing is live.

## Existing automations (DO NOT touch)
- US OPEN  id=94493540-36ef-4ab9-a9fb-06665a038a50  (14:35 UK)  folder=dc92ea4e-66a3-4ef4-a8bd-c2c39ed44d3c
- US MIDDAY id=59f7e6a5-021c-4edd-92f3-dfa2f7e05f5f (17:30 UK)  folder=dc92ea4e-66a3-4ef4-a8bd-c2c39ed44d3c
- US CLOSE id=e73d6c8e-457f-42b3-8177-645e7743e2a8  (20:35 UK)  folder=dc92ea4e-66a3-4ef4-a8bd-c2c39ed44d3c

## Non-negotiable
- No hardcoded compulsory stops, forced liquidation, fixed position limits, or overnight restrictions (those are controller/methodology choices).
- No second broker connection. No LIVE enablement. No credential exposure.

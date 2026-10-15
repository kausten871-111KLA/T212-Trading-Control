# Advanced DEMO order integration candidate - 15 October 2026

## Objective
Integrate previously staged Trading212 stop, limit, stop-limit and cancel methods into
the installed v0.2.1 gateway source while preserving its 600-second metadata cache,
broker GET pacing, current DEMO market-order behaviour and model tool ID.

## Candidate
- Source: openwebui/tools/trading212_demo_gateway.py
- Version: 0.2.2-advanced-orders-candidate
- Added: place_stop_order, place_limit_order, place_stop_limit_order, cancel_order,
  reconcile_order_intent
- Durable SQLite journal with explicit intent_id for these new methods
- Existing MARKET BUY/SELL and close methods AST-identical to installed baseline
- No new trading-strategy constraints. DEMO endpoint fixed.

## Evidence
Network-disabled tests against official Open WebUI image
sha256:9591b13f13843c7721c2b8eaf7382846c81b3ffe126526d1888d1fed50c6a33f:
- test_advanced_legacy_orders.py: 6 PASS
- test_legacy_metadata_cache.py: 14 PASS
- test_legacy_read_recovery.py: 11 PASS
- Official WebUI schema acceptance on isolated candidate: 15 callable methods, 5 added.

T212 official API docs confirm POST equity/orders/limit, equity/orders/stop,
equity/orders/stop_limit and DELETE equity/orders/{id}. Broker acceptance remains pending.

## Production acceptance
1. Exclusive engineering release lock and installed source SHA match.
2. Guarded WebUI admin API update with private snapshot/rollback and grant preservation.
3. Source hash readback and 15 installed callable schemas.
4. DEMO broker acceptance; no LIVE operations.
5. E2 durable market-order intent, E3 independent monitoring and E5 appended decision journal
   remain separate tasks. There is no provider-native modify order endpoint in current docs.

Status: STAGED, OFFLINE-TESTED, SCHEMA-TESTED; NOT DEPLOYED.
No broker calls or production model/schedule modifications were made.

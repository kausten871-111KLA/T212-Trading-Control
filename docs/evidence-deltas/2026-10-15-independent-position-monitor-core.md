# E3: Independent position-monitor core - 15 October 2026

## Goal
Enable DeepSeek Trading Operations to set, revise and withdraw experimental exit
conditions in Trading 212 DEMO and have a deterministic worker evaluate them
between scheduled OPEN/MIDDAY/CLOSE sessions.

## Delivery staged here
- position_monitor_core.py: persistent SQLite decision and event store; broker-position
  pricing evaluator for AT_OR_ABOVE and AT_OR_BELOW; one-shot claim before an exit is
  requested; broker receipt and state recording; reconcile previous unresolved intents
  on subsequent polls; DeepSeek can cancel ACTIVE conditions and register new versions.
- test_position_monitor_core.py: 10 tests passed in a network-disabled official WebUI
  environment, including two concurrent store instances, repeated evaluation, missing
  pricing, controller cancellation/revision, unknown broker result reconciliation,
  invalid input handling, strategy-controlled conditions and multiple watches.

## Why no arbitrary trading constraints
No mandated stop prices, percentages, position caps, EOD liquidation, or trade-count
limits. DeepSeek must explicitly register each exit rule and can revise it by
cancelling an ACTIVE watch and registering another rule.

## Outstanding to become a working daemon
1. Approved authenticated Open WebUI bridge exposing register/cancel/list operations
   from the actual DeepSeek model (do not let non-trading models write rules).
2. Broker adapter calling installed single Trading 212 DEMO gateway
   place_market_order_with_intent / reconcile_order_intent; no parallel broker account.
3. Verify broker position quantity and CURRENT price field, or connect fresh sanctioned
   price feed; if price absent, worker reports unavailable and never invents a quote.
4. systemd/cron worker supervised on the existing VPS. Clock/resilience/secret management,
   rotation of logs, health checks, worker shutdown, and maintenance coordination.
5. Live DEMO acceptance including order result, partials, pending state and broker
   reconciliation. Remain DEMO; LIVE never enabled.

## Scope
This code is a tested execution kernel, NOT a running scheduler. The callbacks
are deliberately not wired to credentials or production order transmission.
No broker calls, credentials, WebUI automations or production models changed.

# E2 Durable market-order intent integration - 15 October 2026

## Deliverable
Add two explicit, caller-ID-based methods to the cached Trading212 DEMO gateway:
- place_market_order_with_intent
- close_position_with_intent

These are new callable methods. The existing place_market_order and close_position
remain intact and retain their operating behaviour for other callers.
When DeepSeek supplies a stable intent_id for a decision, the gateway records
its intent in durable SQLite before broker submission; identical repeated decisions
return existing recorded state rather than submitting another broker POST.
A new legitimate trading decision can use a new distinct intent_id.
No investment-strategy constraints are introduced.

## Tests
Six additional tests with synthetic broker transport and no network:
- BUY broker-confirmed fill
- duplicate intent blocked across Tools instances
- separate genuine decisions with different intent IDs both permitted
- timeout UNKNOWN not retransmitted
- holdings-based close
- LIVE endpoint refused

Depends on PR #15 advanced-order integration, which introduces the journal.
The WebUI configuration and running broker gateway are unchanged.
DEMO broker acceptance and model tool schema deployment are pending.
This is *not* a continuous position monitor.

## Next integration
Update the DeepSeek v5 execution method selection to prefer these explicit
durable methods once installed and inspectable; supply a stable intent_id
per distinct decision, record broker confirmation and unresolved state.
Do not invent IDs when retrying an ambiguous existing decision.

Status: STAGED, NETWORK-DISCONNECTED TESTED, NOT DEPLOYED.

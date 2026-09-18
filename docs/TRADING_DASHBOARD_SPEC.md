# Trading Operations Dashboard Specification

## Top control strip
- Environment: DEMO
- T212 gateway status + gateway version
- Market Data Gateway status + provider/feed
- DeepSeek Fast status
- DeepSeek Batch status
- LIVE: disabled
- last broker action
- last broker verification
- last market-data refresh
- current blocker / degraded dependency

## Account panel
- account value / cash
- open positions
- pending orders
- current P/L where broker supplies it
- recent broker order history
- recent transactions
- broker timestamp / verification timestamp

## Opportunity / Scout panel
- top current gainers
- most-active symbols
- candidate source
- latest price / percentage move
- volume / relative-volume evidence where available
- bid / ask / spread percentage
- market state
- freshness
- SCOUT state: OBSERVE / QUALIFY / REJECT / HANDOFF

## Investigator panel
For each candidate:
- ordinary symbol
- exact T212 instrument mapping when resolved
- catalyst: CONFIRMED / PROBABLE / UNKNOWN
- momentum
- liquidity
- spread
- market/sector support
- exhaustion / late-entry risk
- external confirmation
- evidence timestamp
- missing evidence
- INVESTIGATOR disposition

## Decision panel
- candidate
- lane: intraday / swing / position
- explicit TRADE / REJECT / WAIT
- entry thesis
- invalidation
- intended exposure
- proposed quantity
- confidence/evidence state
- rejection reason
- next owner

## Execution panel
- queued DEMO action
- exact T212 ticker
- intended exposure
- calculated quantity
- pre-submit duplicate check
- broker response
- order/fill state
- verification state
- no-blind-retry flag
- LIVE disabled indicator

## Position control panel
- open DEMO positions
- entry time / average price
- quantity available for trading
- current P/L
- exit logic
- stop/invalidation state
- monitoring status
- pending close action
- broker-verified closure state

## Learning / QA panel
- trades attempted today
- entries verified
- exits verified
- wins / losses
- realised P/L where available
- opportunities rejected
- major greens missed
- missed-green root-cause code
- data/API/orchestration failures
- one next system improvement
- 20-trade validation progress

## Failure taxonomy
Tag material failures:
- DATA
- MARKET
- STRATEGY
- T212_API
- TOOL
- AUTH
- ORCHESTRATION
- EXECUTION
- VERIFICATION
- HUMAN_ACTION

## Source-of-truth rules
- Market Data Gateway supplies discovery/qualification evidence only.
- Trading 212 DEMO is the broker/execution source of truth.
- Model inference is never labelled broker-verified.
- UNKNOWN is preferable to fabricated evidence.
- Historical-order/transaction panels may be first-page snapshots unless pagination is explicitly requested.
- Every broker write must be followed by a read verification.
- T212 order POSTs are non-idempotent; never blind retry.

## Control principle
The dashboard observes and controls one shared T212 DEMO gateway. It must not create a second broker connection.

## Ready-state definition
The dashboard is OPERATIONAL only when:
1. market-data authentication works;
2. candidate discovery works or an exact plan limitation is surfaced;
3. candidate snapshots/quotes can be retrieved;
4. T212 operations dashboard returns broker-verified state;
5. canonical knowledge + five Trading Skills remain attached;
6. DEMO/LIVE separation is verified;
7. the first integrated DEMO loop completes execute -> verify -> monitor -> exit -> verify -> review.

# Read-Only Scanner Test Matrix

## Instrument cache
- first run writes baseline only
- second refresh produces real diff
- ten find_instrument calls use cache
- stale-cache fallback works when metadata read fails
- cache files contain no credentials

## Metrics
- change_pct from price vs previous close
- avg20 volume from last 20 completed daily bars
- relative volume = current day volume / avg20
- dollar volume = price * day volume
- spread percentage uses bid/ask midpoint

## Scanner gates
- +4.9% rejected on move
- +5.0% accepted if all other gates pass
- rel_vol 1.99 rejected
- spread 2.6% watch-illiquid
- spread >5% rejected
- non-T212 symbol rejected
- sub-$0.50 rejected

## Tier state
- first +5% -> newly_qualified true
- +7% no new escalation
- +10% -> escalated true
- restart preserves tier state

## Ledger / queue
- shortlist event persists
- rejected event persists
- only newly qualified/escalated candidates enter catalyst queue

## Missed-green audit
- actual mover absent from surfaced -> NEV
- surfaced rejected -> RET
- qualified/no trade -> NOTRADED
- broker-confirmed fill -> TRADED
- no verified catalyst -> AVOIDED

## Safety
- scanner has no order method
- queue has no order method
- missed-green audit has no order method
- no module contains LIVE broker endpoint
- no broker POST is retried
# DeepSeek Catalyst Handoff Contract

## Trigger
DeepSeek is invoked only when a deterministic scanner candidate is newly qualified or crosses a new movement tier since its last catalyst check.

## Input
Provide only the shortlisted symbol and deterministic facts already computed:
- symbol
- exact T212 ticker
- company name
- exchange/currency
- current price
- change percentage
- relative volume
- dollar volume
- spread percentage
- first-seen time
- latest movement tier
- sector if known
- new-on-T212 flag
- market/feed timestamps

Do not ask DeepSeek to recompute scanner maths.

## DeepSeek task
1. Identify the most likely fresh catalyst.
2. Verify with reliable sources.
3. Classify catalyst type.
4. Explain the business/financial mechanism.
5. Assess whether the move is fundamental/news-driven, sector/macro-driven, technical/noise, manipulation/dilution/high-risk, or unknown.
6. Return a bounded decision object.

## Required output fields
- symbol
- reason_tag
- catalyst_state: confirmed | probable | unknown
- headline
- source
- source_ts
- mechanism
- risk_flags
- disposition: qualify | reject | watch | unknown
- confidence between 0 and 1

## Credit controls
- max 5 catalyst investigations per scanner cycle
- max 20 per day initially
- defer overflow by deterministic rank score
- no repeat investigation unless a new movement tier is crossed or a materially new headline appears

## Source preference
1. company/regulatory primary source
2. exchange/filing
3. recognised financial wire/publication
4. reputable specialist source

Unsourced social posts do not count as confirmation.

## Safety
This handoff never places an order. It only annotates scanner candidates for the downstream DEMO trading workflow.
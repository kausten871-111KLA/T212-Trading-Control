# Trading Operations Dashboard Specification

## Top control strip
- Environment: DEMO
- T212 gateway status
- DeepSeek Fast status
- DeepSeek Batch status
- LIVE: disabled
- last broker action
- last verification

## Account panel
- account value / cash
- open positions
- pending orders
- current P/L

## Opportunity panel
- top current greens
- catalyst
- momentum state
- qualification state
- decision state

## Execution panel
- queued action
- exact T212 ticker
- intended exposure
- calculated quantity
- broker response
- verification state

## Learning panel
- trades today
- wins / losses
- missed greens
- execution failures
- next rule improvement

## Control principle
The dashboard observes and controls one shared gateway; it must not create a second broker connection.

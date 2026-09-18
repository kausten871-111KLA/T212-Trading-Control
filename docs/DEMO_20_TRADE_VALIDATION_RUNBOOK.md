# 20 DEMO Trade Validation Runbook

## Goal
Prove that the Trading Operations system can repeatedly move from market opportunity to broker-verified execution and learning.

## Pass condition
20 controlled DEMO trades completed with:
- explicit candidate;
- evidence-backed rationale;
- T212 exact ticker;
- size;
- broker-confirmed entry;
- broker-confirmed exit;
- recorded result;
- learning review.

## Failure categories
Tag every failure as one of:
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

## Required record
For each attempted trade:
- timestamp
- ordinary symbol
- T212 ticker
- catalyst
- move / momentum
- decision
- rejection reason or entry logic
- exposure
- quantity
- order response
- position verification
- exit logic
- close response
- closure verification
- realised P/L
- issue tag
- learning

## Daily review
- trades completed
- opportunities rejected
- major greens missed
- reason for each miss
- execution faults
- one system improvement for the next session

## Important
The objective is not to manufacture 20 profitable trades. The objective is to validate the process, execution path, controls and learning loop under realistic DEMO conditions.

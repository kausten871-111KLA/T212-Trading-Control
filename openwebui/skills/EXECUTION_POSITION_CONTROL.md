---
name: execution-position-control
description: Execute and verify Trading 212 DEMO orders through the single gateway, monitor positions and close them with broker-side confirmation.
---

# Execution & Position Control

## Purpose
Own the broker lifecycle.

## Sequence
1. Receive explicit DEMO action from Decision Engine.
2. Validate exact T212 ticker.
3. Obtain current quote and FX when monetary exposure must be converted to quantity.
4. Use deterministic sizing.
5. Submit through the single T212 DEMO Gateway Tool.
6. Capture broker response.
7. Verify resulting position/order in T212.
8. Monitor.
9. Close/exit through the same gateway.
10. Verify closure.
11. Return factual result to Learning & QA.

## Rules
- DEMO only.
- Never blind-retry a POST.
- Never infer a fill from a request acknowledgement.
- Never infer closure from a sell submission.
- Never expose credentials.
- LIVE trading remains disabled.

---
name: execution-position-control
description: Execute and verify Trading 212 DEMO orders through the single gateway, monitor positions and close them with broker-side confirmation.
---

# Execution & Position Control

Sequence: receive explicit approved DEMO action -> validate exact T212 ticker -> obtain current quote/FX if needed -> deterministic sizing -> submit through single T212 DEMO gateway -> capture response -> broker read-back verification -> monitor -> exit through same gateway -> verify closure -> return factual result to Learning & QA.

Rules: DEMO only; never blind-retry a POST; never infer a fill from acknowledgement; never infer closure from sell submission; never expose credentials; LIVE remains disabled.

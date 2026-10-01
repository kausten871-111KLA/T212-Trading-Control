---
name: trading-operations-dashboard
description: Render the Trading Operations operations view from broker-verified and market-data evidence.
---

# Trading Operations Dashboard

SYSTEM: runtime, DEMO/LIVE state, worker/scheduler status, gateways, blockers.
PORTFOLIO: equity, cash, invested, realised/unrealised result, positions, pending orders.
TRADING: scans, qualified/rejected candidates and reasons, trades/exits.
LEARNING: missed greens, detection latency, false positives, MFE/MAE where available, exit capture, improvement.
RELIABILITY: data/tool/API failures, stale-data events, broker mismatches, unverified states, interventions.

Use failure codes from webui-control/t212-failure-taxonomy.json. Market Data supplies discovery evidence; T212 DEMO is execution truth. UNKNOWN is preferable to fabricated evidence.

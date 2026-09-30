# Morning Trading Operations Status

The persistent worker should expose a compact machine-readable morning status containing:

- last discovery cycle time / success
- last cache refresh time / instrument count / new instruments
- queue pending / claimed / completed / daily budget
- last EOD audit counts: NEV, RET, NOTRADED, AVOIDED, TRADED
- market-data provider health
- Open WebUI health
- Trading 212 environment: DEMO
- liveTradingEnabled: false
- ordersSubmittedByWorker: report actual DEMO count
- any service/timer failure since prior report

This is the canonical morning handoff between the persistent server worker and ChatGPT/Open WebUI.

# T212 DEMO broker history → FinMem: production acceptance runbook

**22 October 2026 — staged / not deployed.** Existing DEMO trading, four original
automations, five research/broker tool bindings, and LIVE-disabled setting must
be preserved. Do not create a second broker writer or research automation.

## What is actually known

- WebUI's successful Trading Operations automation messages store
  \`function_call\` blocks paired by \`call_id\` with \`function_call_output\`.
- \`recent_order_history\` outputs have the WebUI \`[{"type":"text","text":"<JSON>"}]\`
  envelope. Inner JSON is \`{"items":[{"order":{...},"fill":{...}}], "nextPagePath":...}\`.
- Useful fields: \`order.id,ticker,side,status,currency,filledQuantity,instrument\`;
  \`fill.id,quantity,price,filledAt\`. Do not conflate \`fill.id\` with \`order.id\`
  or per-fill \`fill.price\` with order-average price.
- Eight saved responses showed 21 distinct order IDs across overlapping pages
  (65 total records with repeats). **Saved tool responses are not proof of
  current T212 broker state.** Actual broker outcomes in FinMem remain zero.
- An additional, fifth active WebUI schedule, \`US CONTROLLER — decide & authorise\`,
  appeared on 22 October at 18:45 UTC (zero runs at inspection). Do not silently
  delete it; confirm provenance and potential overlap with four original jobs.
- From 26–30 October, fixed UK times drift an hour later relative to NY; see
  \`runtime/deepseek/us_session_dst_audit.py\`.

## No-order acceptance (requires access to existing authenticated WebUI/T212)

1. Capture fresh SQLite online backup and exact model/tools/automations manifest.
   Record SHA256 fingerprints. Do not use old 3-/4-tool rollback scripts.
2. Verify **DEMO** credentials, one gateway and LIVE-disabled status. Retain all
   existing services and schedules unchanged.
3. In the existing Trading Operations WebUI model only, request **one**
   \`recent_order_history(limit=30)\` read through the existing T212 gateway.
   This must not invoke any place/close/cancel order function. Record the actual
   WebUI call ID and response time privately; do not paste raw order/account
   records in GitHub or chat. Do not infer a fill from model summary text.
4. Inspect the new output via read-only WebUI DB access. Match \`call_id\` and a
   completed assistant message from an authenticated successful run.
5. Run the staged \`runtime/deepseek/t212_history_page_normalizer.py\` over
   previously saved history and over the **fresh authenticated** tool payload.
   The source label remains unverified for saved evidence.
6. The staged \`t212_history_reconciliation.py\` compares broker order ID,
   fill ID, ticker, side, price, quantity, currency, fill timestamp, and evidence
   fingerprint. Only a trusted caller that really made the fresh DEMO request may
   assert \`fresh_authenticated_demo_call=True\` (that flag is not a credential).
   Conflicting, cancelled, partial or multi-fill cases are quarantined.
7. After a separate broker-evidence journal and idempotent importer have passed
   relevant offline and integration tests, import **confirmed executions only**.
   Never write directly into the existing controller's trading-state DB.
8. A research-decision link needs an original recorded decision ID and dated
   causal evidence (intent-to-order correlation), not just the same ticker.
   Do not populate FinMem \`research_outcome\` with mere fill evidence.
9. Independently reconcile fees/FX, opening/closing positions and verified
   realised P&L before recording an actual outcome/reflection.
10. Recheck original job manifests, five tool bindings, system prompt, account
    mode, both DeepSeek services and healthy WebUI. No production claim without
    direct acceptance results.

## Failure policy

- Broker query unavailable: leave live FinMem outcome count unchanged and
  report the explicit read-only acceptance blocker.
- Provider returns multiple fills per order: quarantine; implement fill-level
  evidence journal and aggregation before any import.
- Missing timestamps/currency/IDs or partial order responses: quarantine,
  never fabricate.
- Firewall/SSH/Cloudflare or privileged Ubuntu patches are deferred until
  Contabo's recovery-console access works again.

## Source/test locations

- \`runtime/deepseek/t212_history_page_normalizer.py\`
- \`tests/test_t212_history_page_normalizer.py\`
- \`runtime/deepseek/t212_history_reconciliation.py\`
- \`tests/test_t212_history_reconciliation.py\`
- \`runtime/deepseek/us_session_dst_audit.py\`
- \`tests/test_us_session_dst_audit.py\`

These are staged code and offline contracts, **not** deployed FinMem real-fill
learning or evidence that trading performance has improved.

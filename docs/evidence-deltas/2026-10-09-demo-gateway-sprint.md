# T212 DEMO gateway implementation sprint ? 9 October 2026

STAGED / NOT DEPLOYED. User-authorized coding sprint; isolated branch based on cc276536, preserving the existing production Engineering lane.

Implemented in the self-contained Workspace Tool candidate:
- Typed STOP, LIMIT, STOP_LIMIT and cancellation methods using the official DEMO routes, signed fractional quantities, positive finite inputs, valid time-in-force and explicit stable intent IDs.
- SQLite intent journal committed before transmission, with Linux filesystem locks and mutation pacing. Duplicate intent replay is blocked across instances, processes and restart; changed request contents cannot reuse an identity. Ambiguous outcomes remain UNKNOWN and are not automatically resubmitted.
- Broker status readback and read-only intent reconciliation. Cancellation acceptance never implies a cancelled or unfilled order. Confirmed terminal cancellation settles the original local reservation.
- Broker holdings/pending-order checks plus conservative unresolved local sell reservations.
- Existing fractional market and close interfaces retained. Their legacy process-local duplicate policy is a remaining integration gate.
- Async cache file-lock waits prevent deadlock between separate Tool instances. Fifty warm sequential and ten concurrent lookups are covered. Exact ticker/currency/working-schedule filters retain ambiguous matches explicitly.
- Gateway and worker respect Retry-After numbers/HTTP dates; metadata 429 retries wait at least the documented 50-second interval. Cooldowns above 180 seconds abort rather than retry early.

Functional verification: 28 unittest methods passed in the official v0.11.4 image with Docker network disabled, no broker credentials, and synthetic transports. Coverage includes separate OS processes, crash before response, timeout replay, cancellation races, reservations, validation, fractional market regression, cache refresh concurrency, stale fallback and worker cooldown behavior. Commands and counts are in the JSON receipt. This is executable mocked testing, not static assertion counting or broker acceptance.

Read-only production receipt confirms model trading-operations--deepseek binds trading_212_demo_gateway_tool plus market_data_gateway. Installed gateway SHA-256 4acf6583dd6b41630282de972b5ed20a47705bce477dc2c3a1bd13311712adbe exposes the original ten methods, without pending-order/cancel extensions. No production changes, model/automation changes, orders or paid completions were made.

Remaining gates: legacy MARKET/CLOSE durable integration, manual Pipe FIND cache bypass, installed Open WebUI schema/permission acceptance, effective risk-count policy, shared mount/worker installation, real broker/provider acceptance, reconciliation of UNKNOWN requests without a broker ID, stable account identity across API-key rotation, and distributed/multi-host locking. Working-schedule ID is not proof of an exchange/venue mapping. Aggregate risk and daily loss controls must remain unchanged. PR #7 is separate.

Official references: https://docs.trading212.com/api/orders/placestoporder ; https://docs.trading212.com/api/orders/placelimitorder ; https://docs.trading212.com/api/instruments . Protective orders do not guarantee price or fill.

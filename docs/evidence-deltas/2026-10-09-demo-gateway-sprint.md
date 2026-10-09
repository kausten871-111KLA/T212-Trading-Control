# T212 implementation sprint ? 9 October 2026

Status: STAGED / MOCK-TESTED / ISOLATED-API-TESTED. Not deployed. Draft PR #8.

Implemented STOP, LIMIT, STOP_LIMIT, cancellation and read-only reconciliation. All MARKET/CLOSE/pending-order mutations now share durable pre-transmission SQLite intent identity, single-attempt transmission, sell reservations and pacing. UNKNOWN cannot authorize replay. Exact omitted-ID market/close commands have permanent compatibility keys; distinct approved decisions must use explicit IDs.

Fixed cache cross-instance deadlock, Pipe FIND bypass, long Retry-After handling, minimum metadata retry cooldown and recent successful-refresh cooldown (including force). Generated standalone Pipe reuses the canonical Tool implementation. Added instrument currency/working-schedule filters; schedule identity is not verified exchange mapping.

Aligned only the authorized DEMO position-count policy in the repository risk gate, controls, methodology and validator; retained cash/exposure/loss/aggregate controls. Rejected nonfinite risk inputs. Runtime use is not verified.

Added a guarded WebUI API rollout/rollback script, actual WebUI schema and isolated API/loader/SQLite acceptance, and cache service credential/timeout/cadence corrections. The synthetic admin fixture does not prove actual user permissions.

Validation: 195 full repository tests PASS in the official WebUI v0.11.4 image, network disabled. First-phase 28-test receipt was superseded by this full run. No broker writes, paid model calls or production modifications.

Live readback: model trading-operations--deepseek binds the old trading_212_demo_gateway_tool and market_data_gateway. Installed source SHA256 remains 4acf6583dd6b41630282de972b5ed20a47705bce477dc2c3a1bd13311712adbe; only original ten gateway methods are installed. Cache timer missing; proposed runtime/state paths absent; only existing WebUI data volume mounted. Repository risk gate has tests/config references, but no proved live execution consumer.

See 2026-10-09-gateway-rollout.md for exact rollout, rollback and acceptance gaps; 2026-10-09-executor-prompt.md for the next Engineering execution instruction. PR #7 remains a separate persistent-chat acceptance lane.

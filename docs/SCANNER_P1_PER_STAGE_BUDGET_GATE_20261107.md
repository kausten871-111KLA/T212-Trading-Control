# P1 per-stage inference budget gate ? 2026-11-07

**Review-only contract. No runtime activation, production edits, model invocation, broker access, or schedules.** This document is stacked on draft PR #24; PRs #21?#24 remain unmerged.

## Verified source behaviour

At the reviewed head of PR #24, `ScannerCandidateConsumer.claim_for_model` atomically increments `model_call_budget.calls_reserved` **once per batch claim**, then increments batch attempts. A batch is expected to require two separate model stages, INVESTIGATOR and DECISION. A retry can execute one or both stages again. Therefore the current counter is not an accurate bound on model invocations; **do not raise the default from zero**. No actual invocation API is called by this ledger. `record_verified_stage` accepts only an injected independently trusted host lookup; no production resolver was established. `PhaseService` leaves `model_task_cycle` absent by default, and its scheduled-run observer is not a scanner-stage receipt store.

## Proposed disabled-by-default accounting contract (not implemented)

1. Reserve **one token per actual provider invocation**, immediately before crossing the trusted host-to-model boundary; never reserve one token as a proxy for a two-stage batch. A retry consumes a fresh token even if the same batch/stage is retried. Reserve by UTC day of the attempted call, not the day a batch was staged.
2. Maintain durable rows with unique invocation ID, batch ID, stage, attempt/lease generation, UTC day, reservation time, and state (`reserved`, `dispatched`, `terminal_verified`, `uncertain`). Enforce uniqueness of each invocation ID and atomic daily limit under SQLite `BEGIN IMMEDIATE`. Keep a separate daily aggregate or derive counts from the rows. Forbid caller-supplied self-reported costs as authority.
3. Treat crash-after-reservation and timeout-after-dispatch as **spent/uncertain** rather than refunding and retrying free. Only allow a refund if the trusted host can prove dispatch never occurred; safer initial implementation is never to refund.
4. Each stage must carry its own invocation ID, matching authenticated host terminal receipt, batch ID, ordered candidate IDs and lease generation. DECISION can only start after an independently verified completed INVESTIGATOR receipt. A late receipt from an expired/replaced lease cannot authorize cursor ACK.
5. Before invocation, require both positive explicit owner budget authorization and a configured trusted host callback; `DEFAULT_MAX_CALLS_PER_UTC_DAY=0` remains the default. A nonzero budget alone is not permission to execute.
6. Enforce the cap across **all consumers using the same model account**, not merely this local SQLite file, or document an upstream centralized quota that does. Daily count is a maximum number of attempted calls, **not a currency ceiling**; tokens and actual cost require independently verified metering and a second separate cost guard.
7. On host/provider outage, invalid receipt, untrusted source, missing candidate policy, or exhausted cap, fail closed: persist state, leave cursor unchanged, do not infer a successful model result and do not place any order.

## Acceptance cases before any deployment

- Budget zero denies every stage including retries and restart.
- With cap 1, the first stage may reserve once but the second stage must be blocked; with cap 2, exactly two distinct stages may reserve, not a third retry.
- Two processes competing for the last token must result in exactly one successful reservation.
- Reservation survives restart; a timeout or unknown outcome still consumes the token.
- UTC midnight rollover is based on attempted invocation time; prior-day reservation never disappears.
- Forged receipts, wrong batch IDs, wrong candidate set, stage-order inversion, stale lease and replayed invocation IDs never advance cursor.
- The host adapter proves its own authentication and immutable receipt provenance; synthetic unit-test callbacks are not production evidence.
- Provider-level daily call counts and token/currency metering reconcile with durable reservations in supervised non-order acceptance.

## Owner decisions and stop gates

Methodology owner/DeepSeek must explicitly approve deterministic candidate admission/exclusion, repeat-alert handling, max candidates per cycle, and a maximum of **actual model calls** per UTC day including retries. Identify the existing authorised WebUI invocation method, authenticated per-stage terminal receipt store and trusted host-side resolver before writing an adapter. No such evidence was confirmed in this sprint. Do not wire a second invoker, turn on polling, merge PRs, or deploy.

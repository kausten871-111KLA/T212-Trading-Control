# P1 isolated crash/restart and missing-stage acceptance ? 7 Nov 2026

**Draft only. No production deployment or model invocation.** Based on draft PR #26 at b879a1fb8cbad33ad0f698bbc79f673accc0515c, stacked on PR #25, #24, #23, #22 and #21.

Five new synthetic SQLite tests pass:
1. Restart after staging before claim retains pending state; zero budget prevents claim.
2. Restart after claim prevents another worker claiming before lease expiry; expired lease can be reclaimed.
3. Restart after persisted INVESTIGATOR receipt but without DECISION rejects cursor ACK.
4. Restart after both persisted synthetic receipts does not auto-ACK; explicit complete ACK is still required.
5. Missing independently injected DECISION resolver fails closed; cursor remains unchanged.

The 10 existing P1 ledger tests and 5 earlier concurrency tests also pass: **20 total passing tests** in this isolated checkout. These are test doubles, NOT authenticated WebUI receipts and NOT a live end-to-end acceptance. No provider, broker, network API or external model was invoked by tests.

## Further review gate
Persisted stage receipts are keyed by batch and stage, not by attempt/lease generation. Before permitting actual retries, the methodology/invocation owner must decide and test whether a stage completion from an earlier expired lease may be reused, and if so verify it is for the identical immutable batch and authentic terminal model invocation; otherwise fence receipt provenance by attempt/lease generation. This is a potential cross-attempt trust-boundary gap, not a demonstrated production failure. The earlier per-invocation cost-accounting gap and absent independent authenticated scanner-stage receipt resolver remain blockers.

No model budget change: default zero. No cursor advancement occurred outside temporary test databases. Production checkout is untouched. Do not merge/deploy.

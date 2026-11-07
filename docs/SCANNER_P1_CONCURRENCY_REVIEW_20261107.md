# P1 isolated concurrency and evidence-integrity sprint ? 7 November 2026

**Status: DRAFT / review only. Not merged or deployed. No production candidate state touched.**

Based on draft PR #23 at commit d2874dfe592a79d13dcb12c2690321c112b73d3f. The Contabo production runtime, scanner, services, broker settings, schedules and WebUI tools were not changed.

## Narrow finding

The staged ScannerCandidateConsumer.stage_page uses a SHA-256 batch identity covering consumer name, starting/ending cursor and ordered candidate IDs. Its original repeat-page path returned an existing batch ID without checking whether the full scanner evidence for those same IDs had changed.

This is a **stage/replay integrity ambiguity**, not evidence that production observations have ever changed. The first staged payload remained intact, but a caller could mistake a semantically changed page for an exact idempotent replay.

## Isolated change

For an existing batch ID, compare the new candidate records with the originally persisted records within the same SQLite write transaction; reject a semantic difference with ConsumerError. This intentionally does not require the response max_id_at_read to stay identical: the scanner can discover newer events while older page evidence remains unchanged.

No cursor advancement or receipt logic changed, no model call path added, and the default daily inference budget remains zero.

## Actual offline tests

- Five new synthetic tests on throwaway SQLite: simultaneous identical-page staging is idempotent; concurrent divergent pages cannot replace an outstanding page; concurrent separate SQLite connections cannot claim the same batch twice; same candidate IDs with changed record evidence are rejected while benign max_id_at_read movement is accepted; and expired leases reject the previous worker's receipt.
- Ten existing scanner-ledger/bridge synthetic tests also passed after the change.
- Simultaneous callers use independent SQLite connections from separate threads, not separate Linux processes. No provider/model/broker/schedule interaction occurred.
- git diff --check passed.

## Remaining gates

The existing authenticated WebUI INVESTIGATOR and DECISION terminal receipt sources remain unverified. No host receipt lookup is wired. Methodology owner has not defined deterministic admission thresholds or an actual two-stage/retry model-call budget. Do not merge or deploy until review of draft dependency PR #21 ? PR #22 ? PR #23 ? this PR, receipt provenance, and model cost accounting.

Overnight continuations should skip this already completed concurrence/replay test and select one other unfinished safe engineering task. Avoid overlap with the existing 07:30 Trading & WebUI scheduled sprint.

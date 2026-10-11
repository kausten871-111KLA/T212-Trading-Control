# Catalyst recovery implementation — 11 October 2026

Status: STAGED / offline-tested. Not deployed. Isolated PR10 continuation from 3027515ba10f99a7ba3e1d9dd58e39627e043702. Existing Engineering retains production ownership.

## Delivered
- Fenced claim tokens: missing, expired or replaced tokens cannot acknowledge or retry another worker's event. Consumer uses current time and reports lost leases instead of false completion.
- Per-event attempt cap and persisted daily review-attempt budget, including conservative legacy accounting. A crash consumes its reserved attempt; repeated provider work is bounded.
- Queue completion atomically retains result plus review outbox. Locked, fsynced atomic review projection recovers after process death before/after replacement or before export acknowledgement, without duplicate receipts.
- Malformed queue/projection data and conflicting receipts fail closed and preserve evidence.
- Provider-free recovery CLI and pre-session-gate recovery. Scanner event and scan identifiers survive review export.

## Exact acceptance
From checkout root:
```sh
python3 -m unittest discover -s tests -p 'test_catalyst*.py' -v
python3 -m unittest discover -s tests -p 'test_scan_event_correlation.py' -v
python3 -m unittest discover -s tests -p 'test_review_log_durability.py' -v
```
28 + 1 + 2 = 31 PASS; 17 newly added recovery methods. Raw output: docs/evidence-deltas/2026-10-11-catalyst-recovery-stdout.txt.
Includes real child os._exit crash points, four concurrent exporters, lost/expired lease fencing, replacement failure, corrupt/conflicting files, legacy migration, daily attempt accounting and two provider-free CLI invocations. No broker/provider network calls. Historical195 not rerun. These counts overlap earlier suites; do not add them to45 as unique tests.

## Engineering next executable acceptance
Review/integrate queue and consumer together in an isolated worktree, then run the three commands above. Against disposable COPIES of existing queue/log files:
```sh
python3 worker/run_catalyst_consumer.py --recover-reviews-only --queue /tmp/t212-disposable/queue.jsonl --review-log /tmp/t212-disposable/reviews.jsonl
```
Run twice. Expected: provider_calls=0; first run exports outstanding receipts; second adds no duplicate. Preserve exact stdout and file hashes. Do not use production paths for this acceptance.

Compatibility: acknowledge/retry now require current lease tokens. Existing untokened claims must expire and be reclaimed; do not mix old consumer and new queue. max_per_day also bounds review attempts, not only candidate ingress. Preserve approved configuration and review this tightened contract. Before any eventual installation retain source and queue/log backups, drain/coordinate sole worker, validate copied-state recovery, and preserve state on rollback; never downgrade while a new worker is active.

## Limits and remaining work
Local single-host POSIX filesystem assumptions; no hardware power-loss or production mount validation. Projection rewriting is O(history) per receipt. Provider execution before queue acknowledgement can repeat after a crash, within caps; no exactly-once remote inference claim. Corrupt state requires deliberate repair, not silent deletion. PR7 database scheduler occurrence loss is independent and remains unfixed. Trusted broker/FX producer and integrated positive BUY admission remain outstanding; BUY containment stays in place. Full broker decision/outcome/learning event correlation remains incomplete.

A45 progresses at source/test level; all50 action statuses remain0 complete/15 in progress/29 queued/6 blocked. No parent runtime acceptance promoted. No production, schedule, broker, security or paid-provider changes.

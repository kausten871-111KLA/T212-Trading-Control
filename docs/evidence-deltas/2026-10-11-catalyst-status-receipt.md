# Catalyst consumer status receipt durability — isolated follow-up to PR #10

**Status:** STAGED / ISOLATED-TESTED; not installed, not integrated into a production worker. Independent follow-up branch based on PR #10 commit `e10bd60ea72290399430cabff020415fea5fe0b3`. Engineering remains the production owner.

## Finding and change

PR #10 safely persists catalyst queue and review outbox, but `worker/run_catalyst_consumer.py:atomic_json` originally used one predictable `.tmp` pathname and `Path.write_text -> chmod -> replace` without a status-write lock, file fsync, parent directory fsync, or destination symlink rejection. This is status-report durability, not order or review receipt authority.

The isolated follow-up replaces this path with an exclusive local POSIX file lock, unique no-follow O_EXCL private temporary output, fsync before replace, parent directory fsync after replace, symlink rejection and cleanup on failed replacement. Non-finite JSON fails before modifying the old receipt.

## Reproducible tests

From the isolated checkout:

```sh
docker run --rm -i --network none --read-only --tmpfs /tmp:rw,nosuid,nodev,mode=1777 -e WEBUI_SECRET_KEY=synthetic-test-only -e PYTHONPATH=/app/backend:/work -v /tmp/t212-support-pr10-e10bd60:/work:ro -w /work --entrypoint python ghcr.io/open-webui/open-webui:v0.11.4 -m unittest discover -s tests -p 'test_catalyst*.py' -v
# Ran 33 tests ... OK (5 new status tests)
# Same image/flags with '-p test_scan_event_correlation.py' -> Ran 1 ... OK
# Same image/flags with '-p test_review_log_durability.py' -> Ran 2 ... OK
```

**36 targeted tests passed** in official WebUI v0.11.4 with network disabled. Additional manual recovery: provider-free CLI run twice on disposable COPIES of a synthetic completed queue event: first delivered 1 receipt, second 0, identical review-log hash, `provider_calls=0` and `orders_submitted=0`. There were no existing catalyst queue/log production files in checked paths; no historical-data migration accepted.

## Limitations

- Does not address trusted broker/FX producer, integrated risk admission or the intentionally BLOCKED BUY path.
- Does not repair PR #7 scheduler occurrence-loss crash window, account-wide risk reservations, nor deploy cache/runtime.
- POSIX local filesystem assumptions only; hardware/power-loss, remote/NFS locks and actual WebUI provider/user acceptance not established.
- This isolated patch is not PR #10 itself and is not an Engineering production-lease acknowledgement.

**Next:** Engineering review stacked patch, integrate queue and consumer together, test on disposable copies of actual queue/log history once available; separately implement trusted BUY admission and PR #7 transactional occurrence repair before any production promotion.

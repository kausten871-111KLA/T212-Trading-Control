# Open WebUI v0.12.3 supervised upgrade — 20 October 2026

This package rebases the **existing user-approved** Open WebUI scheduler/tool-binding patch onto the official pinned `v0.12.3` image. The trading controller and gateway remain separate services. No new broker or automations are created.

## Exact images

- Production before upgrade: `local/open-webui-toolbinding-stage:20261020`, image `sha256:0477e56acd1174ee042f24f21401877a68a5fa6793caa0261c0fb9a025e18f84`.
- Official source: `ghcr.io/open-webui/open-webui@sha256:a537bbe1e6b428820f52ed4a029d7fff97062e24d5cf32c365fba36fd0542def`.
- Rebased candidate: `local/open-webui-toolbinding-v0123-stage:20261020`, image `sha256:7d8d04ead2b7c38d99b12b80a777b6030f3c694c491ca93e6bb010b5c3e82483`.

## Evidence (staging-only; no broker orders)

- Extracted v0.11.4 patched `automations.py`, `middleware.py`, `automation_tool_contract.py` and exact v0.12.3 upstream files. SHA256 asserted in `rebase_webui_v0123.py`. Preserved upstream Tool Search and terminal automation status implementation.
- Rebased candidate Python AST tests passed, pinned Docker build passed.
- Copied 220 files including validated *internal-only* Hugging Face relative symlinks into an isolated `data-clean` directory. SQLite online backup/integrity OK, 43 original tables.
- Started candidate on `--network none` with the **copy** and no broker credentials. It migrated to 48 tables, responded HTTP 200 on localhost, and retained all three original active OPEN/MIDDAY/CLOSE schedules.
- Resolved actual model-associated T212 DEMO, Alpaca and Contabo tools through v0.12.3 `get_tools`: **28 functions**. Verified full model tool-ID recovery and server capability inventory. `v0123_acceptance.py` PASS on isolated app.
- Practised SQLite rollback on a second isolated 48-table copy. Restored the verified pre-upgrade 43-table backup with `v0123_restore_db.py`; integrity OK.
- The staging network was disabled and no model inference, gateway orders or LIVE trading occurred.

## Supervised production cutover

The only user-facing command, on Contabo as `katie`, is:

```bash
bash /home/katie/webui-v0123-stage-20261020/upgrade_supervised.sh --check
bash /home/katie/webui-v0123-stage-20261020/upgrade_supervised.sh --deploy
```

`--deploy` first snapshots the entire production WebUI data volume and creates a SQLite-consistent database backup under a **new** timestamped `/home/katie/backups/webui-v0123-cutover-...` folder. It saves the current Compose YAML, replaces the exact image line only, recreates the single existing WebUI container with `--pull never`, awaits health, performs read-only 28-function + 3-automation acceptance, verifies private bridge token and both running services, and reports `UPGRADE_PASS` or invokes automatic Compose/SQLite rollback.

**No v0.12.3 candidate should be switched on production before the full snapshot succeeds.**

## Manual rollback

The deploy script prints `BACKUP_DIR=...` and the complete `ROLLBACK_CMD=`. Use that **exact** command if reverting after a successful initial deployment. It stops WebUI before restoring the original pre-migration database and original Compose image, then checks health. The original private `.env` is preserved throughout. Never roll back only the Docker image after a v0.12.3 migration.

## Constraints

- Preserve T212 **DEMO**, all original OPEN/MIDDAY/CLOSE automation IDs, persistent DeepSeek dispatcher, Alpaca and Contabo bridge, and LIVE disabled.
- `v0123_acceptance.py` loads function descriptors only; it does not execute brokerage calls.
- Stage `data-clean` and backup directories are private Contabo data **and must not be committed to GitHub**.
- See existing PR #21 and Issue #20 for deployment evidence and the still-open autonomous `trading_ready:false` controller linkage.

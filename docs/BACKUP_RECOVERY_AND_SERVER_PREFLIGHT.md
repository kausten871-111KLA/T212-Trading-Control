# Backup, recovery and server preflight

This runbook reduces the remaining Contabo/OpenWebUI check to one read-only command. It does not deploy, restart containers, alter the database, place orders, or print environment variables.

## Safety boundary

- Trading remains `DEMO` only.
- `live_trading_enabled` and `order_mutation_enabled` must both be `false`.
- Never paste Trading 212 keys, OpenWebUI secrets, Docker environment output, session cookies, or SSH private keys into chat or an issue.
- A failed or unavailable check returns `NOT_READY` and exits non-zero.

## One-command readiness check

In the Contabo SSH terminal, from the checked-out repository, replace `APPROVED_SHA` with the exact 40-character commit supplied in the morning handoff:

```bash
python3 scripts/server_deployment_preflight.py --repo-dir . --expected-commit APPROVED_SHA
```

Success is a JSON report with `"status": "READY"`, no entries in `failed_checks`, and `"side_effects": "none"`.

The command verifies:

1. the expected feature branch and exact commit;
2. a clean Git worktree;
3. the OpenWebUI container is running;
4. the live WebUI database exists and is non-empty;
5. recent non-empty database and tool-table backups exist;
6. at least 1 GiB is free on the repository filesystem;
7. the repository's full test/configuration preflight passes; and
8. the release manifest remains DEMO-only with live trading and order mutation disabled.

If the container or data directory differs, supply the known values explicitly:

```bash
python3 scripts/server_deployment_preflight.py --repo-dir . --container open-webui --data-dir /app/backend/data --expected-commit APPROVED_SHA
```

## Backup inventory (read-only)

The preflight expects these files inside the OpenWebUI data directory:

- `webui.db`
- at least one `webui_backup_*.db`
- at least one `tool_table_backup_*.json`

By default, the newest backup of each type must be no more than 24 hours old and non-empty. The report prints only the backup basename, byte size and age; it does not print database or tool contents.

## Recovery discipline

Do not restore over the active database as an overnight or automated action. Recovery is a controlled human-approved operation:

1. stop all WebUI writers;
2. preserve the current database under a new timestamped name;
3. validate the selected backup with SQLite integrity checks in a disposable copy;
4. record the source backup name, size and checksum;
5. restore only after explicit approval;
6. restart and verify login, workspace visibility, tool registry and DEMO-only safety;
7. retain both the pre-restore database and the source backup until acceptance.

The preflight intentionally does not implement restore or container restart commands. Those actions can overwrite active state and require a separate, explicit recovery approval.

## Interpreting failures

| Failed check | Meaning | Safe next action |
|---|---|---|
| `expected_branch` | Wrong checkout | Switch only after confirming no local work |
| `clean_worktree` | Uncommitted server changes | Preserve and review; do not reset |
| `expected_commit` | Server code differs from approved SHA | Review fetch/fast-forward path |
| `container_running` | Docker/OpenWebUI unavailable | Inspect container status and logs |
| `database_present` | Database missing or empty | Stop; locate the configured data volume |
| `database_backup` | Backup missing, empty or stale | Create/verify a fresh backup before changes |
| `tool_table_backup` | Tool export missing, empty or stale | Export and verify before changes |
| `disk_space` | Less than 1 GiB free | Free space without deleting project/user data |
| `repository_preflight` | Tests or config validation failed | Fix branch-side and rerun |
| `demo_safety` | Trading boundary is not safe | Stop; restore DEMO-only fail-closed settings |

## Rollback point

The approved Git commit is the code rollback anchor. The newest validated database and tool-table backups are the state rollback anchors. Record all three identifiers before any later deployment. No deployment is authorised by this document.

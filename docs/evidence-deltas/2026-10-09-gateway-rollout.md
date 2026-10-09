# Engineering rollout and rollback

This is a tested candidate, not a production deployment. PR #8 targets feature/t212-instrument-cache-v03. The isolated worktree is /home/katie/t212-gateway-sprint-20261009; the original checkout is unchanged.

## Live baseline, 9 October

Model trading-operations--deepseek attaches trading_212_demo_gateway_tool and market_data_gateway. Installed gateway SHA256: 4acf6583dd6b41630282de972b5ed20a47705bce477dc2c3a1bd13311712adbe. Installed gateway still has its original ten methods.

The cache timer is not installed (systemctl is-enabled: not-found; is-active: inactive). /home/katie/t212-scanner and /var/lib/t212-scanner do not exist. The container has only its existing data volume at /app/backend/data, backed by /var/lib/docker/volumes/open-webui_open-webui-data/_data. Do not interpret repository deployment paths as running infrastructure.

## Rollout steps

1. Engineering acknowledges exclusive production ownership and verifies no conflicting rollout or broker workflow. Review the latest PR commit and its acceptance receipt. Back up the production data volume using the existing cold-backup procedure.
2. Preserve the journal directory on persistent storage. Current namespace is SHA256(API key) scoped, not account-ID scoped. Do not rotate credentials or introduce another key for the same account without preserving/reconciling all outstanding intents. Multi-host/NFS locking is not accepted.
3. Choose shared cache storage explicitly: provision the documented host state path and bind it to /app/backend/data/t212-scanner, or configure the worker to use the existing volume's t212-scanner subdirectory. Confirm identical cache/lock files from host and container, permissions/ownership and backup coverage. Do not silently replace the existing data volume. The cache worker must use the same effective storage as the Tool/Pipe.
4. Provision the release directory (the source worktree is not the runtime release) and private /etc/t212/demo-cache.env for the worker. Never commit or print credentials. The staged service requires this environment file, allows up to 12 minutes for four 30-second attempts plus three 180-second provider cooldowns, and avoids automatic restart loops. Its referenced runtime/state paths still require installation. Install/enable the timer only after shared storage and read-only worker acceptance; record cache age/source and metadata count.
5. Use scripts/rollout_t212_gateway.py with WEBUI_ADMIN_TOKEN supplied securely. It uses the official WebUI update API and preserves metadata/access grants, refuses an unexpected source hash, defaults to read-only preflight, and saves a private exclusive backup before applying. Run on the server using a verified loopback WebUI URL. The script's source check is not an atomic server-side CAS; exclusive ownership remains required.

```bash
python3 scripts/rollout_t212_gateway.py --url http://127.0.0.1:8080 --expected-sha 4acf6583dd6b41630282de972b5ed20a47705bce477dc2c3a1bd13311712adbe
```

After preflight and ownership confirmation, add --apply --backup /a/private/new-backup.json --owner-lease <actual-owner-reference>. Verify the URL/port before use. Rollback uses --rollback <that-backup> --owner-lease <actual-owner-reference> and refuses to overwrite intervening source changes. A lost update response is reconciled with GET; it is not retried automatically. A failed verification remains a deployment exception and requires owner review.

6. Verify the installed source hash, method schemas, existing model binding, real user's tool permissions and a cache-only FIND through the actual model. The isolated tests use a synthetic admin; they do not prove live user's access or provider invocation. Expose new typed methods through the Workspace Tool. The generated manual Pipe is a separate interface: rebuild with scripts/build_t212_demo_pipe.py before any Pipe import, and verify its separate binding/permissions.
7. Update callers to stable explicit intent_id values. MARKET/CLOSE remain callable without them for compatibility, but the derived key permanently blocks repeated identical commands across restart. A distinct approved decision must use a new explicit ID; never use a new ID to retry UNKNOWN.
8. Trace the deployed risk consumer. git grep finds repository risk-gate use in tests/config references, not a verified running execution consumer. The count-only policy correction is staged; do not claim the effective trading cap changed until the actual consumer is wired and accepted. Preserve every other risk control.
9. Perform broker/provider acceptance only through the existing authorized DeepSeek owner and workflow. No synthetic trade is required to finish installation acceptance. STOP may slip; STOP_LIMIT can trigger without filling. Readback must distinguish pending/partial/fill/cancel/reject/expiry/UNKNOWN. Acceptance is not a fill.

## Known boundaries

UNKNOWN without broker ID requires manual broker history/position reconciliation. API-key identity and filesystem locks are single shared-host assumptions. Successful metadata snapshots enforce a shared 50-second cooldown even for forced refresh; retries honour provider waits and metadata cooldowns. There is no durable cross-key/provider-wide attempt budget across failed separate refresh invocations. Venue aliases need authoritative mapping; workingScheduleId is not proof of exchange identity. Persisted order identity does not implement the complete portfolio risk policy by itself. PR #7 persistent-chat acceptance remains separate.

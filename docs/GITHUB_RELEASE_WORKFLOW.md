# GitHub-backed Validation and Release Workflow

## Outcome

Every control-plane change can now be checked automatically in GitHub and with
one read-only command. The workflow does not deploy, access Open WebUI, use
secrets or contact Trading 212.

## Automatic checks

For control-plane, tool, test or verifier changes, GitHub Actions:

1. checks out the exact commit;
2. compiles Python sources;
3. runs the complete unit suite;
4. runs the integrated preflight;
5. rejects tracked `.env` or dotenv variants.

The workflow has only `contents: read` permission. It contains no deployment
job and receives no repository secrets.

## One-command manual preflight

On the Ubuntu server or a clean Linux checkout:

```bash
python scripts/verify_webui_control.py
```

Success is:

- exit code `0`;
- JSON report with `"status": "PASS"`;
- `"live_effect": false`;
- T212 environment `DEMO`, LIVE `false`, order mutation `false`;
- zero test failures.

Do not paste API keys, secrets or the contents of environment files into the
terminal command or chat.

## Release boundary

The release manifest is intentionally `STAGED_NOT_DEPLOYED`. Passing CI proves
source consistency; it does not authorise deployment.

Deployment still requires:

- exact commit selection;
- clean CI/preflight result;
- confirmed WebUI database and tool-table backup evidence;
- explicit human approval;
- a recorded rollback path.

## Minimal future human action

When deployment is ready, Katie should only need to approve the exact commit and
run one prepared server command in the existing Contabo SSH window. That command
must be generated only after the target paths and current deployed version have
been verified. The current work does not ask her to paste credentials or alter
LIVE trading access.

## Rollback

The CI workflow can be disabled by reverting its feature-branch commit. The
staged manifest and verifier have no live effect. Any later server deployment
must use the pre-recorded Open WebUI database/tool-table backups for rollback.

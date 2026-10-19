# Open WebUI automation tool capability — staging gate (19 October 2026)

**STAGED / NOT DEPLOYED**. These files are an implementation candidate tied to the
installed Open WebUI v0.11.4 fork, not an automatic installation script.
DeepSeek retains all trading decisions. Neither DEMO nor LIVE orders are issued
by these files.

## Incident evidence
- OPEN 13:35 UTC 19 October: 7 function calls, none invoking T212/Alpaca;
  the generated text nevertheless asserted execution tools were unavailable.
- MIDDAY 16:30 UTC: same custom model, broker dashboard/list_positions/list_orders
  and Alpaca scanner/snapshots/quotes tools were invoked successfully.
- The persisted custom model has both tool IDs and the stored tool owner, model owner,
  and automation owners match. A global detachment is contradicted.
- The exact runtime cache and provider-advertised function inventory at OPEN were
  not captured, so transient cache drift versus model self-diagnosis is unproved.

## Integration changes
1. `automations.patch` changes `_resolve_model_defaults()` in the installed
   scheduler: if the runtime model cache lacks the *key* `toolIds`, fall back
   to saved workspace metadata. If explicit cached bindings contradict those saved,
   fail the scheduled run before launching a model call. Does not bypass owner
   or tool access checks.
2. `middleware.patch` checks actually resolved server-side `tools_dict` against
   saved configured local tool IDs for scheduled automations. It fails with an
   explicit error if tools disappear and sends a short server-derived function-name
   inventory to DeepSeek if they resolve. No tool is called by the check.
3. `automation_tool_contract.py` is the dependency-free side-effect-free helper.

## Reproduction / verification
Staged installed-source copies:
`/home/katie/t212-automation-tool-preflight-review-20261019/open_webui/utils/`

Original source SHA256:
- `automations.py` 0f1d962ba85496497d957d55de60d4530aa8cc9a724a597c2cb62975889d19fd
- `middleware.py` bda81a45b4169ec2af351c3eed7a574b0e43cf1026c3d6945dada7290a5af497

Staged:
- Source replacements matched exactly once; both modified files passed AST parse.
- **13/13** contract tests extracted the *actual installed scheduler function* and
  proposed middleware guard from staged source and exercised both with mocks.
- **Same-image ephemeral Docker import test PASSED**, image
  `sha256:9591b13f13843c7721c2b8eaf7382846c81b3ffe126526d1888d1fed50c6a33f`,
  `--network none --read-only`, disposable SQLite DB under `/tmp`, dummy
  test-only secret, patched source files mounted read-only. No real WebUI data
  volume, credentials, model calls, broker calls, or production writes.
- Repository tests: `python -m unittest discover -s tests -q`.

## Rollout constraints
These are zero-context unified diffs. After verifying the exact source SHA-256,
review the hunks and use `git apply --unidiff-zero --check` first inside an
isolated WebUI source checkout; never bypass a source mismatch.
WebUI fork source is not itself a tracked PR21 component. These patches must be
reviewed and applied to an exact matching WebUI source checkout by the exclusive
installation owner, with fresh backup, rollback and controlled mock run. Do not
apply to the live Docker container with `docker exec`. A successful scheduler
dispatch does NOT prove broker execution: completion and outcome receipts remain
separate RT-14 obligations. There is no established full live-model reproduction,
and therefore this patch is NOT a confirmed production cure.

**No new schedules, broker connections, trading policy or LIVE access.**

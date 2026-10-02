# Evidence delta — fail-closed pre-open readiness gate (2026-10-02)

## Scope

- Register IDs: T01–T12, D01–D07, M01–M12, A01–A09, F01–F05
- State: **STAGED**
- Tested implementation commit: `ac2a7711cd1c52b02740305b6dac0244ca89c3e2`
- Runtime deployment: **not evidenced**

## Bounded change

A deterministic pre-open gate now reduces the Trading Operations readiness surface to 18 explicit dependencies. Every dependency is classified `PASS`, `FAIL`, or `MISSING`; the aggregate decision is `GO` only when there are no failures and no missing items.

The gate:

- requires current runtime evidence (maximum 15 minutes old), dashboard evidence (maximum 5 minutes old), and acceptance evidence (maximum 24 hours old);
- fails closed on unsafe environment evidence, LIVE enablement, stale data, unverified cache baselines, missing broker/account truth, missing scheduler ownership, missing monitoring, or missing session authority;
- treats session authority as an explicit acceptance item and never infers it from installed code or historical success;
- performs no provider, model, broker, or order calls and reports `orders_submitted_by_gate=0`;
- starts from a non-secret acceptance template in which every check is `MISSING`;
- adds the readiness artefact to the runtime-evidence inventory and release manifest.

## Files

- `scripts/build_preopen_readiness.py`
- `tests/test_preopen_readiness.py`
- `webui-control/preopen-acceptance-evidence.template.json`
- `scripts/collect_runtime_evidence.py`
- `openwebui/tools/trading_dashboard_evidence.py`
- `webui-control/release-manifest.json`

## Verification

GitHub Actions run 82 completed successfully against the exact implementation commit:

- Python compilation: PASS
- Complete unit suite: **149 tests PASS**
- Control-plane preflight: PASS
- Reported safety state: `environment=DEMO`, `live_trading=false`, `order_mutation=false`
- Discovery smoke output: `orders_submitted=0`
- Empty-evidence gate acceptance: `decision=NO_GO`, `PASS=0`, `FAIL=0`, `MISSING=18`, exit code 2 as designed
- Tracked dotenv audit: PASS

CI evidence: https://github.com/kausten871-111KLA/T212-Trading-Control/actions/runs/36967201290

## Interpretation boundary

This proves the repository gate is deterministic and fail-closed. It does **not** prove that the Contabo checkout is synchronized, that the intended runtime is running this commit, that market/broker evidence is fresh, or that Friday's unattended DEMO session is authorized or ready. The present runtime decision therefore remains **UNPROVEN**, not GO.

## Exact next item

Prepare a single non-secret server-side command that collects current runtime evidence, rebuilds the trading dashboard, evaluates all 18 checks, and prints only the GO/NO-GO decision plus evidence paths. It must remain read-only/no-order and stop on any missing prerequisite.

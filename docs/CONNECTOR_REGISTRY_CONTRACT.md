# Connector Registry Contract

## Scope

This registry covers only the integrations currently required by the four
active WebUI workspaces:

- GitHub engineering/source control;
- provider-neutral model and vision routing;
- workspace-scoped Open WebUI file visibility;
- Trading 212 DEMO technical readiness.

It is an allow-list, not a plugin discovery catalogue. A connector absent from
the registry is denied.

## Installation boundary

The registry does not install software or activate integrations. A connector
may be activated only after:

1. its source is verified;
2. requested permissions match the registry;
3. secrets exist only in the server secret manager/environment;
4. its read-only health check passes;
5. a rollback path is recorded;
6. any required human approval is captured.

Repository URLs, package versions and hashes must be recorded before any future
third-party installation. Broad capability scouting and unverified repositories
are outside this contract.

## Connector controls

| Connector | Current state | Write boundary |
|---|---|---|
| GitHub | connected | Feature-branch writes only; protected/default branch actions require approval |
| Model provider/router | staged | Inference only; provider/model changes require approval |
| Open WebUI file store | staged | New versions allowed; source overwrite/delete/public sharing denied |
| T212 DEMO readiness | staged | Read-only; LIVE and all order mutations denied |

## T212 invariant

The validator rejects any registry state that:

- targets a non-DEMO environment;
- enables LIVE trading;
- enables order creation, modification or cancellation;
- permits automatic retry of an order POST;
- exposes LIVE credentials.

Any future DEMO execution bridge remains separate and requires Katie's exact,
immutable human approval under the existing trading controls.

## Verification

From a clean checkout:

```bash
python -m unittest discover -s tests -p 'test_plugin_registry.py'
```

Before live activation, run each connector's declared read-only health check and
write the evidence to the durable workspace handoff. A failed or missing health
check blocks use; it does not trigger an automatic install or permission
expansion.

## Rollback

Because this registry is additive, GitHub staging changes no live WebUI state.
If a future deployment fails, disable the connector integration and restore the
pre-deployment WebUI configuration/database backup. Do not delete source files
or user work.

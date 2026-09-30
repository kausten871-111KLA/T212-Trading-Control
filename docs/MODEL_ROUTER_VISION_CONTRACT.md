# Model Router and Vision Contract

## Purpose

Route each Open WebUI task to a server-configured logical model role without
putting provider credentials or concrete production model IDs in GitHub.

This is a control-plane component only. It does not call a model, install a
provider, or change the live Open WebUI configuration.

## Non-negotiable behaviour

1. Images, screenshots, scans and rendered PDF pages require the `vision`
   capability.
2. A text-only model must never be presented as vision-capable by metadata.
3. If no genuine vision role is configured, the task is blocked and reported.
4. Secrets are never passed through prompts or stored in route logs.
5. High-stakes medical/scientific, financial, legal, publishing and deployment
   work retains an explicit human-review gate.
6. Route decisions are logged with model role, required capabilities, fallback
   status, cost tier and any blocking reason.

## Server-side bindings

Set these only in the server secret/environment manager:

- `WEBUI_MODEL_FAST_TEXT`
- `WEBUI_MODEL_DEEP_REASONING`
- `WEBUI_MODEL_VISION`
- `WEBUI_MODEL_HIGH_CAPABILITY`

The values are provider/model IDs already approved for the relevant workspace.
No API key belongs in these variables or in the repository.

## Current routing

| Input/task | Logical role | Safety behaviour |
|---|---|---|
| Image, screenshot, scan, PDF page image | vision | Blocks if the vision binding is absent |
| Science review, architecture, final QA | high_capability | Human review where required |
| Classification, tagging, extraction, summaries | fast_text | Low-cost deterministic preference |
| Reasoning, drafting, planning, coding | deep_reasoning | Default reasoning path |

Visual input takes priority over task type. For example, “extract this
screenshot” routes to `vision`, not `fast_text`.

## Verification before deployment

Run:

```bash
python -m unittest tests.test_model_router
```

Then perform four read-only WebUI smoke tests:

1. text-only extraction selects the fast-text binding;
2. coding selects the deep-reasoning binding;
3. a screenshot selects the genuine vision binding;
4. temporarily remove the vision binding and confirm the screenshot task is
   blocked with no text-only fallback.

Record the smoke-test evidence in the workspace handoff. Do not activate the
router in production until all four checks pass and a rollback copy of the
current WebUI model configuration exists.

## Rollback

This component is additive. Until deployment it changes no live behaviour.
After deployment, rollback means restoring the pre-change WebUI model
configuration and disabling the router integration; the logical contract and
test files can remain in GitHub for diagnosis.

---
name: apps-integration-governance
description: Audit-first, least-privilege governance for Apps / Plugins / Bots engineering.
---

# Apps / Plugins / Bots Governance

## Required controls
- Audit existing capability before creating a duplicate integration.
- Prefer small vertical slices: build -> test -> verify -> connect -> scale.
- Branch-first for code/configuration changes.
- Keep credentials and secrets server-side and outside prompts/GitHub.
- Apply least privilege and workspace scoping.
- Do not install unverified repositories or broad capability packs.
- Record endpoint/dependency/version/permission/test evidence for every integration.
- A configured integration is not operational until a real bounded test passes.
- Preserve rollback and existing working components.
- External spending, account/security changes and irreversible actions require explicit approval.

## Evidence
Return exact test result, blocker/root cause and next action; never use a prompt/config file alone as proof of operation.

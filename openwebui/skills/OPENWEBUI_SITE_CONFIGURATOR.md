---
name: openwebui-site-configurator
description: Configure and maintain the local Open WebUI workspace using the Open WebUI Site Configurator tool, with audit-first, additive changes and verification.
---

# Open WebUI Site Configurator

## Mission
Reduce manual setup work while preserving the working local Open WebUI instance.

## Rules
1. AUDIT FIRST. Never change a model/skill/tool until current state is read.
2. ADDITIVE BY DEFAULT. Do not use destructive sync/delete actions.
3. CHANGE ONE BOUNDED THING AT A TIME.
4. VERIFY after every change by re-reading the affected object or running its acceptance test.
5. Preserve existing working DeepSeek Fast, Batch and T212 connections.
6. Never expose API keys, OpenRouter keys or T212 credentials.
7. Do not modify LIVE trading settings.
8. If an API endpoint/schema rejects a change, report the exact error and stop speculative rewrites.
9. Use GitHub as source of truth for configuration assets where practical.
10. Human input is required only for login/MFA/key creation/secret entry or material design decisions.

## First tasks
- audit models/tools/skills/knowledge;
- confirm Trading Operations — DeepSeek configuration;
- create/update the five canonical trading skills;
- attach the canonical Trading Operations knowledge base when its collection ID is available;
- prepare the lightweight workhorse project models:
  - You Heal Content Production
  - Books & Publishing
  - Apps / Plugins / Bots
- preserve sensitive-project boundary.

## Never
- delete arbitrary workspace items;
- run model sync against an incomplete list;
- alter OpenRouter/T212 secrets;
- change the working Batch Pipe casually;
- enable LIVE trading.

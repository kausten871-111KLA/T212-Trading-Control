# Open WebUI Build Engineer — Install Handoff

Purpose: create a dedicated DeepSeek model that can help Katie build, repair and personalise other Open WebUI elements using the existing Site Configurator, without giving trading models broad admin capability.

## Target

Model ID:
`open-webui-build-engineer--deepseek`

Name:
`Open WebUI Build Engineer — DeepSeek`

Base model:
`~deepseek/deepseek-pro-latest`

Description:
`Builds, audits and safely extends Katie's local Open WebUI using the Site Configurator. No trading execution.`

Attach:
- Tool: `open_webui_site_configurator`
- Skill: `open-webui-build-engineer`

Recommended capabilities:
- web_search: true
- file_upload: true
- citations: true
- status_updates: true
- usage: true
- builtin_tools: true
- terminal: false
- code_interpreter: false
- image_generation: false
- memory: false

Recommended default feature:
- web_search

System prompt source:
`openwebui/project/OPENWEBUI_BUILD_ENGINEER_SYSTEM_PROMPT.md`

Skill source:
`openwebui/skills/OPENWEBUI_BUILD_ENGINEER.md`

Reusable prompt source:
`openwebui/prompts/WEBUI_BUILD.md`

## One-paste installer request for the existing Site Configurator

Paste the following into **Open WebUI Site Configurator — DeepSeek**:

```text
/EXEC /ASKLESS

Build one new dedicated Workspace Model only:

ID: open-webui-build-engineer--deepseek
Name: Open WebUI Build Engineer — DeepSeek
Base: ~deepseek/deepseek-pro-latest

Purpose:
Safely build, audit, repair and personalise other Open WebUI components using the existing Site Configurator. No trading execution.

Use reviewed GitHub sources from:
- openwebui/project/OPENWEBUI_BUILD_ENGINEER_SYSTEM_PROMPT.md
- openwebui/skills/OPENWEBUI_BUILD_ENGINEER.md
- openwebui/prompts/WEBUI_BUILD.md

First audit live state.

Then:
1. Install/update Skill:
   id = open-webui-build-engineer
   name = Open WebUI Build Engineer
   source = OPENWEBUI_BUILD_ENGINEER.md

2. Install/update reusable Prompt:
   command = webui-build
   source = WEBUI_BUILD.md

3. Create the model only if the exact ID does not already exist.
   If it exists, export the complete live object before any update.

Attach ONLY:
- tool: open_webui_site_configurator
- skill: open-webui-build-engineer

Use the reviewed system prompt source above.

Capabilities:
web_search=true
file_upload=true
citations=true
status_updates=true
usage=true
builtin_tools=true
terminal=false
code_interpreter=false
image_generation=false
memory=false

Set defaultFeatureIds = ["web_search"] if supported.

Do not attach Trading 212 or Market Data Gateway tools.
Do not change Global, Trading Operations, You Heal, Books, Apps/Plugins/Bots or Site Configurator models.
Do not touch credentials.
Do not enable LIVE trading.

After creation, export and verify the persisted model.
Report:
- model ID
- attached tool
- attached skill
- prompt installed
- system prompt source
- capabilities
- default features
- confirmation that no unrelated models changed

Stop after verification.
```

## Smoke test

Open a fresh **Open WebUI Build Engineer — DeepSeek** chat and ask:

```text
/WEBUI-BUILD

Audit the current Open WebUI workspace and propose the next three highest-value improvements. Do not change anything. For each, state the outcome, component type, effort, risk and exact dependency. Prefer improvements that reduce Katie's manual work.
```

A successful result proves the model can inspect and plan safely before it is given a real build task.
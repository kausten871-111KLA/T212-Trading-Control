# Self-Configuring Open WebUI — Local Setup

## Objective
Allow a dedicated DeepSeek workspace model to audit and perform bounded additive configuration work on the local Open WebUI instance, reducing repetitive manual clicking.

## Security model
The configurator uses a temporary Open WebUI API key stored only in the local server process as:
OPENWEBUI_ADMIN_API_KEY

Do not paste this key into chat, GitHub, model prompts or Tool source.

Open WebUI API keys act as the user who created them. For this initial local setup, use the admin key temporarily, perform configuration, then revoke/rotate it. A dedicated lower-permission service account is preferable for long-term operation.

## User-only setup
1. Admin Panel -> Settings/Admin -> Authentication -> enable API Keys if currently disabled.
2. Settings -> Account -> create/copy the Open WebUI API key.
3. Stop Open WebUI with Ctrl+C in the same PowerShell session.
4. Load the key using a secure prompt into OPENWEBUI_ADMIN_API_KEY.
5. Restart Open WebUI in that same PowerShell session.

## Tool
Create Workspace -> Tools -> Open WebUI Site Configurator using:
openwebui/tools/openwebui_site_configurator.py

## Configurator model
Create a custom Workspace Model:
Name: Open WebUI Site Configurator — DeepSeek
Base: proven DeepSeek Fast/OpenRouter model
System: concise configuration/engineering role
Attach:
- Open WebUI Site Configurator Tool
- openwebui-site-configurator Skill
Capabilities:
- Tools ON
- Status Updates ON
- Citations ON
- Web Search ON
- Terminal OFF initially
- Memory OFF
- LIVE trading irrelevant/disabled

## First acceptance test
Prompt:
"Audit this Open WebUI workspace. Do not change anything. Report the custom models, skills, tools and knowledge collections, then identify the smallest additive configuration tasks still required for Trading Operations."

Pass condition:
The agent calls audit_workspace and accurately reports live workspace state.

## Second acceptance test
Ask it to create one harmless test/configuration skill, verify it appears, then either retain it if useful or remove it manually. Do not start with model-wide changes.

## Why this route
Open WebUI exposes authenticated REST endpoints for custom model export/import and workspace resources. The configurator can therefore perform repetitive workspace setup inside the local instance instead of forcing the user to click every item manually.

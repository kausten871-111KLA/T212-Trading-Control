# Local OpenWebUI baseline — 2026-10-01

This is a read-only inventory of the known-good local OpenWebUI database under
`C:\Users\katie\open-webui-data\webui.db`. It is evidence of the local
baseline only and is **not** evidence that the remote Contabo instance has the
same registrations.

## Registered tools

| ID | Name | Notes |
|---|---|---|
| `market_data_gateway` | Market Data Gateway | Read-only market-data path; no broker writes |
| `trading_212_demo_gateway_tool` | Trading 212 DEMO Gateway Tool | Single DEMO broker gateway; LIVE disabled |
| `open_webui_site_configurator` | Open WebUI Site Configurator | Bounded additive WebUI configuration tool |

## Registered project models

### Trading Operations — DeepSeek
ID: `trading-operations--deepseek`

- knowledge: `Trading Operations Canonical v2`
- tool IDs:
  - `trading_212_demo_gateway_tool`
  - `market_data_gateway`
- skill IDs:
  - `trading-cito-orchestrator`
  - `market-intelligence`
  - `trading-decision-engine`
  - `execution-position-control`
  - `learning-qa`
  - `shared-portfolio-ledger`
  - `trading-operations-dashboard`
  - `autonomy-safety-guardrails`
- web search enabled
- automation capability enabled
- memory disabled

### Apps / Plugins / Bots — DeepSeek
ID: `apps-plugins-bots--deepseek`

- knowledge: none
- tool IDs: none
- skill IDs:
  - `open-webui-build-engineer`
- memory disabled

### You Heal Content Production — DeepSeek
ID: `you-heal-content-production--deepseek`

- knowledge: none
- tool IDs: none
- skill IDs: none
- memory disabled

### Books & Publishing — DeepSeek
ID: `books-publishing--deepseek`

- knowledge: none
- tool IDs: none
- skill IDs: none
- memory disabled

### Open WebUI Site Configurator — DeepSeek
ID: `open-webui-site-configurator--deepseek`

- tool IDs:
  - `open_webui_site_configurator`
- skill IDs:
  - `open-webui-site-configurator`
  - `autonomy-safety-guardrails`
- automation capability enabled

## Important interpretation

A model/tool/skill registration in the database proves configuration only.
Operational proof still requires runtime evidence: model response, tool call,
state/output artifact, broker/API evidence where relevant, and timestamped
handoff/ledger output.

The remote deployment must be audited against this baseline rather than assumed
to match it.

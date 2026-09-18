# Trading Operations Workspace Model Setup

## Why this layer exists
The proven T212 Pipe Function is retained as the direct human/manual broker control console.
The Workspace Tool is the agent-callable broker layer. DeepSeek can call its methods from a custom Workspace Model.

## Create the tool
Workspace -> Tools -> Create.
Paste:
openwebui/tools/trading212_demo_gateway.py

No credential entry is required. It reads the already-loaded server environment variables:
- T212_DEMO_API_KEY
- T212_DEMO_API_SECRET

## Create the model
Workspace -> Models -> Create.

Name:
Trading Operations — DeepSeek

Base model:
Use the already-proven DeepSeek Fast/OpenRouter model.

System prompt:
Paste openwebui/project/TRADING_OPERATIONS_SYSTEM_PROMPT.md

Attach the Trading 212 DEMO Gateway tool.

Recommended capabilities:
- Tools: on
- Web Search: on once a search provider is configured
- Citations: on
- Status Updates: on
- Memory: off for this operational trading model unless deliberately required
- LIVE trading: no tool exists; disabled by architecture

## Tool responsibilities
- trading_dashboard: account/positions/orders
- find_instrument: broker ticker resolution
- size_quantity: deterministic £/currency exposure -> quantity calculation from supplied quote + FX
- place_market_order: broker write; DEMO only
- close_position: full DEMO close
- list_positions/list_orders: verification

## Human/direct fallback
The existing Pipe Function remains selectable as Trading 212 DEMO Execution for manual commands and diagnostic recovery.

## Acceptance test
Ask the custom Trading Operations model:
"Use your Trading 212 DEMO tool to show me the current trading dashboard. Do not place an order."

A pass means DeepSeek calls the Workspace Tool itself and accurately reports the broker state.

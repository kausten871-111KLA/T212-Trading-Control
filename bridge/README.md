# ChatGPT ↔ Open WebUI MCP Bridge

This folder contains a narrow, local-first MCP bridge for Katie's Open WebUI instance.

## Purpose

Allow a supported ChatGPT custom-app/MCP client to:

- confirm Open WebUI health;
- list models;
- list automations;
- inspect automation runs;
- send a message into an approved Open WebUI model;
- optionally run an existing automation.

The bridge talks only to the local Open WebUI API (default `http://127.0.0.1:8080`).

## Security defaults

- Reads the existing Open WebUI API key from `OPENWEBUI_API_KEY` or `OPENWEBUI_ADMIN_API_KEY`.
- `BRIDGE_ALLOW_WRITES=false` by default.
- `BRIDGE_ALLOW_TRADING=false` by default.
- Trading/broker model IDs are blocked from `send_message` unless explicitly enabled.
- `BRIDGE_ALLOWED_MODELS` can restrict chat to a comma-separated model allow-list.
- Do not expose the Open WebUI port itself to the public internet.

## Install locally

PowerShell:

```powershell
uv pip install -r bridge/requirements.txt
```

Run from the repository root:

```powershell
$env:OPENWEBUI_BASE_URL="http://127.0.0.1:8080"
uv run python bridge/openwebui_mcp_bridge.py
```

The MCP server uses Streamable HTTP and normally exposes its MCP endpoint at:

```
http://127.0.0.1:8000/mcp
```

## Safe first configuration

Keep writes and trading disabled:

```powershell
$env:BRIDGE_ALLOW_WRITES="false"
$env:BRIDGE_ALLOW_TRADING="false"
$env:BRIDGE_ALLOWED_MODELS="open-webui-site-configurator--deepseek,you-heal-content-production--deepseek,books-publishing--deepseek,apps-plugins-bots--deepseek"
```

Then start the bridge and test `bridge_health`.

## Remote ChatGPT connection

A local MCP server cannot be called directly by ChatGPT. Use a supported secure MCP tunnel or another private remote transport. Do not expose localhost/Open WebUI directly.

Current OpenAI plan availability must be checked before connection. The bridge can be prepared independently of plan support.

## Later acceptance gates

Only after read-only testing passes:

1. allow `send_message` to approved non-trading models;
2. optionally set `BRIDGE_ALLOW_WRITES=true` for automation control;
3. keep `BRIDGE_ALLOW_TRADING=false` until a separate explicit trading-bridge acceptance test;
4. preserve Trading Operations DEMO/LIVE-disabled controls independently of this bridge.

## Tools exposed

- `bridge_health`
- `list_models`
- `list_automations`
- `get_automation_runs`
- `send_message`
- `run_automation` (blocked unless writes are enabled)

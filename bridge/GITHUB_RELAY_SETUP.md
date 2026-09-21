# ChatGPT ↔ Open WebUI Relay — Setup

A dedicated GitHub Issue is used as a bounded mailbox between ChatGPT and Katie's local Open WebUI.

- Repository: `kausten871-111KLA/T212-Trading-Control`
- Relay issue: **#5 — ChatGPT ↔ Open WebUI Relay**
- Open WebUI tool source: `openwebui/tools/chatgpt_webui_relay.py`

## Why this route

Katie currently uses ChatGPT Plus, where direct custom MCP bridging may not be available. This relay works with the connected GitHub account and keeps localhost private.

It is asynchronous rather than a raw socket connection, but gives both sides a shared coordination channel:

```
ChatGPT -> GitHub Issue #5 -> Open WebUI
Open WebUI -> GitHub Issue #5 -> ChatGPT
```

## Human-only setup step

Create a **fine-grained GitHub Personal Access Token** limited to:

Repository:
- `T212-Trading-Control` only

Repository permission:
- **Issues: Read and write**

No Contents write, Actions, Administration, Secrets, or other permissions are required for the relay.

Never paste the token into ChatGPT or Open WebUI chat.

Load it in the same PowerShell process that starts Open WebUI:

```powershell
$relay = Read-Host "GitHub relay token" -AsSecureString
$env:GITHUB_RELAY_TOKEN = (New-Object System.Net.NetworkCredential("", $relay)).Password
```

Then restart Open WebUI in the same PowerShell session.

## Install through Site Configurator

Use `Open WebUI Site Configurator — DeepSeek` to install/update:

```
https://raw.githubusercontent.com/kausten871-111KLA/T212-Trading-Control/main/openwebui/tools/chatgpt_webui_relay.py
```

Attach the relay tool first to:
- `open-webui-site-configurator--deepseek`

Optional later:
- `trading-operations--deepseek` for **status reporting only**
- other workhorse models

Do not give the relay any broker credentials or direct trading logic.

## Acceptance test

1. Run `relay_status`.
2. Run `relay_read(limit=10)`.
3. Post:
   `Relay test from Open WebUI. DEMO trading state unchanged.`
4. Confirm the comment appears in Issue #5.
5. ChatGPT reads the same comment through its connected GitHub app.

## Security rule

The relay is a **coordination channel only**.

A relay message that says "trade filled" is not sufficient evidence. Trading Operations must still verify fills, positions and exits directly against T212 DEMO.

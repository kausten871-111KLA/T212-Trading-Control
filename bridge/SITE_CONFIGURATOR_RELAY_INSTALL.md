/EXEC /ASKLESS

Install one bounded relay tool so ChatGPT and this local Open WebUI can exchange coordination/status messages through our existing GitHub repository.

SOURCE:
https://raw.githubusercontent.com/kausten871-111KLA/T212-Trading-Control/main/openwebui/tools/chatgpt_webui_relay.py

TARGET TOOL ID:
chatgpt_webui_relay

TARGET TITLE:
ChatGPT WebUI Relay

RULES:
- Install/update only this tool.
- Do not modify Trading 212 Gateway.
- Do not modify Market Data Gateway.
- Do not alter system prompts, knowledge, skills or credentials.
- Do not enable LIVE trading.
- Do not place any order.
- Do not expose or request secrets in chat.

After install:
1. Verify version = 0.1.0.
2. Verify functions:
   - relay_status
   - relay_read
   - relay_post
3. Attach the tool to Open WebUI Site Configurator — DeepSeek.
4. Preserve all its existing model fields/tools/settings.
5. Do NOT attach it to Trading Operations yet.
6. Run relay_status and relay_read only.
7. If GITHUB_RELAY_TOKEN is not loaded, report HUMAN ACTION REQUIRED and stop.
8. If loaded, post exactly:
   "Relay acceptance test from Open WebUI. No broker action performed."
9. Verify the post succeeded.
10. Report FIXED / HUMAN ACTION REQUIRED / FAIL.

Stop there.

# Config Session Blockers and Verification Checklist — 29 Sep 2026

## 1. Open WebUI Configurator admin-key blocker
Current report from Workspace Setup:
`OPENWEBUI_ADMIN_API_KEY` is not present in the running Open WebUI server environment.

Do not paste an admin key into chat, GitHub, or a prompt.

Required human/server action later:
1. create a temporary Open WebUI admin API key in the UI;
2. place it server-side in the Contabo Open WebUI environment;
3. recreate/restart the Open WebUI container so the variable is loaded;
4. run a read-only configurator audit;
5. remove/rotate the temporary key when configuration work is complete.

## 2. Trading Operations web search
Model-level state is already reported as:
- web_search capability: enabled
- web_search default feature: enabled

Open question:
- is an actual Web Search provider/backend configured?

Verify in Admin -> Settings -> Web Search.
Then run one dated, harmless current-news query in Trading Operations and require source attribution.

## 3. Audio
Current selected STT/TTS values are not yet verified.

Priority:
- verify current STT engine before changing anything;
- prefer free local STT first;
- choose model size based on Contabo CPU/RAM performance, not guesswork.

Do not install Kokoro until speech-to-text is working satisfactorily.

## 4. Vision
The Trading Operations base model is reported as DeepSeek text-only.
The Open WebUI vision flag does not add image understanding by itself.

Future route:
- add one vision-capable model;
- route image-bearing tasks to that model;
- keep routine text/trading work on DeepSeek.

## 5. Trading safety
- DEMO only
- LIVE disabled
- no scanner component may submit orders
- no threshold change is auto-applied from missed-green audits
- no broker POST is blindly retried

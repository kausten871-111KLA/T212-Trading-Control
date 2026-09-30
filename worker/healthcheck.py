#!/usr/bin/env python3
import json, os, time
from pathlib import Path
state=Path(os.getenv("T212_SCANNER_STATE_DIR","/var/lib/t212-scanner"))
status=state/"status.json"
try:
    payload=json.loads(status.read_text(encoding="utf-8"))
    age=time.time()-status.stat().st_mtime
    ok=bool(payload.get("ok")) and age < 900
    print(json.dumps({"ok":ok,"statusAgeSeconds":round(age,1),"status":payload}))
    raise SystemExit(0 if ok else 1)
except Exception as exc:
    print(json.dumps({"ok":False,"error":str(exc)}))
    raise SystemExit(1)

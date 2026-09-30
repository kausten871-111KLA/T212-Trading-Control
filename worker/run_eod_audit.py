#!/usr/bin/env python3
"""End-of-day missed-green audit runner. No orders."""
import json, os
from datetime import datetime, timezone
from pathlib import Path

STATE=Path(os.getenv("T212_SCANNER_STATE_DIR","/var/lib/t212-scanner"))
OUT=STATE/"eod_audit_latest.json"

def load_json(path,default):
    try:return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:return default

def main():
    actual=load_json(STATE/"actual_movers.json",[])
    surfaced=load_json(STATE/"surfaced_candidates.json",[])
    traded=load_json(STATE/"broker_fills.json",[])
    sm={str(x.get("t212_ticker") or x.get("symbol") or "").upper():x for x in surfaced}
    tm={str(x.get("t212_ticker") or x.get("symbol") or "").upper():x for x in traded}
    rows=[]
    for mover in actual[:100]:
        key=str(mover.get("t212_ticker") or mover.get("symbol") or "").upper()
        s=sm.get(key); t=tm.get(key)
        if not s: code,reason="NEV","never surfaced"
        elif t: code,reason="TRADED","broker-confirmed trade exists"
        elif s.get("scanner_state")=="rejected": code,reason="RET","surfaced but rejected by deterministic gate"
        elif s.get("catalyst_state") in ("unknown","unverified","none"): code,reason="AVOIDED","surfaced without verified catalyst"
        else: code,reason="NOTRADED","surfaced and qualified but not traded"
        rows.append({"symbol":mover.get("symbol"),"change_pct":mover.get("change_pct"),"audit_code":code,"audit_reason":reason})
    counts={}
    for r in rows:counts[r["audit_code"]]=counts.get(r["audit_code"],0)+1
    payload={"ts":datetime.now(timezone.utc).isoformat(),"counts":counts,"rows":rows,"orders_submitted":0}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(payload,indent=2),encoding="utf-8")
    print(json.dumps({"ok":True,"counts":counts}))
    return 0
if __name__=="__main__":raise SystemExit(main())

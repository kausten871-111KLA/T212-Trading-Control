#!/usr/bin/env python3
"""Daily Trading 212 DEMO instrument-cache refresh. Read-only."""
import json, os, sys, time
from pathlib import Path
import urllib.request, base64

DATA_DIR=Path(os.getenv("T212_SCANNER_STATE_DIR","/var/lib/t212-scanner"))
CACHE=DATA_DIR/"t212_instrument_cache.json"
DIFF=DATA_DIR/"t212_instrument_diff.json"
LOCK=DATA_DIR/"t212_instrument_cache.lock"
URL="https://demo.trading212.com/api/v0/equity/metadata/instruments"

try:
    import fcntl
except ImportError:
    fcntl=None

def atomic(path,payload):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(payload,indent=2,default=str),encoding="utf-8")
    tmp.replace(path)

def load(path):
    try: return json.loads(path.read_text(encoding="utf-8"))
    except Exception: return None

def diff(previous,current):
    prev={str(x.get("ticker")):x for x in previous if isinstance(x,dict) and x.get("ticker")}
    cur={str(x.get("ticker")):x for x in current if isinstance(x,dict) and x.get("ticker")}
    added=[cur[t] for t in sorted(set(cur)-set(prev))]
    removed=[prev[t] for t in sorted(set(prev)-set(cur))]
    result={
        "generatedAtEpoch":time.time(),
        "baselineWasPresent":bool(previous),
        "addedCount":len(added) if previous else 0,
        "removedCount":len(removed),
        "added":added if previous else [],
        "removed":removed,
    }
    return result

def main():
    key=os.getenv("T212_DEMO_API_KEY","").strip()
    secret=os.getenv("T212_DEMO_API_SECRET","").strip()
    if not key or not secret:
        print("ERROR: T212 DEMO credentials unavailable",file=sys.stderr); return 2
    DATA_DIR.mkdir(parents=True,exist_ok=True)
    with LOCK.open("a+") as lock:
        if fcntl is not None: fcntl.flock(lock.fileno(),fcntl.LOCK_EX)
        previous_payload=load(CACHE) or {}
        previous=previous_payload.get("instruments",[])
        token=base64.b64encode(f"{key}:{secret}".encode()).decode()
        req=urllib.request.Request(URL,headers={"Authorization":f"Basic {token}","Accept":"application/json"})
        with urllib.request.urlopen(req,timeout=30) as response:
            current=json.loads(response.read().decode("utf-8"))
        if not isinstance(current,list):
            raise RuntimeError("unexpected T212 instrument response")
        atomic(CACHE,{"provider":"Trading212","environment":"DEMO","fetchedAtEpoch":time.time(),"count":len(current),"instruments":current})
        d=diff(previous,current)
        atomic(DIFF,d)
        print(json.dumps({"ok":True,"instrumentCount":len(current),"diff":{k:d[k] for k in ("baselineWasPresent","addedCount","removedCount")}}))
        if fcntl is not None: fcntl.flock(lock.fileno(),fcntl.LOCK_UN)
    return 0
if __name__=="__main__": raise SystemExit(main())

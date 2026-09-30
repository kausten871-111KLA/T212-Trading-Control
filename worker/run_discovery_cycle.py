#!/usr/bin/env python3
"""Bounded deterministic worker shell. Read-only by default; no broker orders."""
import json, os, sys, time, traceback
from datetime import datetime, timezone
from pathlib import Path

STATUS_PATH=Path(os.getenv("TRADING_WORKER_STATUS","/var/lib/t212-scanner/status.json"))
LOG_PATH=Path(os.getenv("TRADING_WORKER_LOG","/var/lib/t212-scanner/worker.jsonl"))

def atomic_json(path,payload):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(payload,indent=2,default=str),encoding="utf-8")
    tmp.replace(path)

def log(event,payload=None):
    LOG_PATH.parent.mkdir(parents=True,exist_ok=True)
    row={"ts":datetime.now(timezone.utc).isoformat(),"event":event,"payload":payload or {}}
    with LOG_PATH.open("a",encoding="utf-8") as h:
        h.write(json.dumps(row,default=str)+"\n")

def main():
    started=datetime.now(timezone.utc)
    status={"started_at":started.isoformat(),"mode":"READ_ONLY","ok":False}
    try:
        # Placeholder orchestration shell: deterministic scanner modules are invoked
        # after live market-data discovery availability is verified.
        status.update({
            "ok":True,
            "finished_at":datetime.now(timezone.utc).isoformat(),
            "message":"worker shell healthy; discovery adapter not yet armed",
            "live_trading_enabled":False,
            "orders_submitted":0,
        })
        log("worker_health",status)
        atomic_json(STATUS_PATH,status)
        return 0
    except Exception as exc:
        status.update({
            "finished_at":datetime.now(timezone.utc).isoformat(),
            "error":f"{type(exc).__name__}: {exc}",
            "traceback":traceback.format_exc(),
        })
        log("worker_error",status)
        atomic_json(STATUS_PATH,status)
        return 1

if __name__=="__main__":
    raise SystemExit(main())

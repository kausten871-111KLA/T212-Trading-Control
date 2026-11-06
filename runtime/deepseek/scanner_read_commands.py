"""Bounded, strictly read-only scanner access for authenticated bridge commands.

The scanner event store is not modified. The returned cursor is an explicit
caller-managed acknowledgement: persist next_cursor only after the consumer
successfully handles the response. Reads never silently advance anything.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import sqlite3
import subprocess

SCANNER_ROOT=Path("/home/katie/.local/state/deepseek-runtime")
SCANNER_DB=SCANNER_ROOT/"market_scanner.sqlite3"
HEALTH_JSON=SCANNER_ROOT/"market_scanner_health.json"
MAX_ITEMS=12
DEFAULT_ITEMS=5

def _as_cursor(value):
    if isinstance(value,bool):
        raise ValueError("cursor must be an integer")
    try:
        number=int(value)
    except (TypeError,ValueError,OverflowError):
        raise ValueError("cursor must be an integer") from None
    if number < -1 or number > 2**63-1:
        raise ValueError("cursor out of range")
    return number

def _as_limit(value):
    if isinstance(value,bool):
        raise ValueError("limit must be an integer")
    try:
        number=int(value)
    except (TypeError,ValueError,OverflowError):
        raise ValueError("limit must be an integer") from None
    return max(1,min(MAX_ITEMS,number))

def _connect():
    if not SCANNER_DB.is_file():
        raise FileNotFoundError("scanner_db_absent")
    db=sqlite3.connect("file:"+str(SCANNER_DB)+"?mode=ro",uri=True,timeout=2)
    db.execute("PRAGMA query_only=ON")
    return db

def _load_json(s, fallback):
    try:
        out=json.loads(s)
        return out if isinstance(out,type(fallback)) else fallback
    except (ValueError,TypeError):
        return fallback

def scanner_candidates(cursor=-1,limit=DEFAULT_ITEMS):
    """Read a page of scanner evidence; -1 starts with the most recent page.

    Cursor is an event ID. Reuse next_cursor on the following call, but only
    after the consuming DeepSeek automation has processed/recorded this page.
    """
    try:
        pos=_as_cursor(cursor)
        count=_as_limit(limit)
    except ValueError as e:
        return {"ok":False,"error":"invalid_pagination","detail":str(e)}
    try:
        with _connect() as db:
            max_id=int(db.execute("SELECT COALESCE(MAX(id),0) FROM candidates").fetchone()[0])
            if pos==-1:
                rows=db.execute(
                    "SELECT id,symbol,asof,observed_at,signal_kinds,evidence FROM candidates "
                    "ORDER BY id DESC LIMIT ?",(count+1,)).fetchall()
                rows=list(reversed(rows[:count]))
                has_more=False
                start_mode="recent_bootstrap"
                # This intentionally starts with the newest N; older events
                # remain in SQLite and can be fetched with cursor=0.
            else:
                rows=db.execute(
                    "SELECT id,symbol,asof,observed_at,signal_kinds,evidence FROM candidates "
                    "WHERE id>? ORDER BY id ASC LIMIT ?",(pos,count+1)).fetchall()
                has_more=len(rows)>count
                rows=rows[:count]
                start_mode="incremental"
            records=[]
            for id_,symbol,asof,first_observed,kinds_text,evidence_text in rows:
                evidence=_load_json(evidence_text,{})
                returns=evidence.get("returns_pct") or {}
                volumes=evidence.get("volume_by_window") or {}
                vwap=evidence.get("vwap_by_window") or {}
                halt=evidence.get("halt") or {}
                records.append({
                    "id":id_,"symbol":symbol,"market_bar_asof":asof,
                    "first_detected_at":first_observed,
                    "signals":_load_json(kinds_text,[]),
                    "price":evidence.get("price"),
                    "feed":evidence.get("feed"),
                    "returns_pct":{k:returns.get(k) for k in ("1","5","15","30","60")},
                    "volume_1m":volumes.get("1"),"volume_5m":volumes.get("5"),
                    "vwap_5m":vwap.get("5"),
                    "day_change_pct":evidence.get("day_change_pct"),
                    "relative_minute_volume":evidence.get("minute_volume_anomaly"),
                    "volume_vs_prior_day":evidence.get("day_volume_vs_prior"),
                    "breakout_15m":evidence.get("breakout_15"),
                    "halt_status":halt.get("status","unknown"),
                    "sample_age_seconds":evidence.get("sample_age_seconds"),
                })
            next_cursor=records[-1]["id"] if records else max(0,pos)
            return {
                "ok":True,"command":"scanner_candidates",
                "source":"scanner_sqlite_read_only","mode":start_mode,
                "cursor_requested":pos,"next_cursor":next_cursor,
                "max_id_at_read":max_id,"returned":len(records),
                "has_more":has_more if pos!=-1 else (max_id>next_cursor),
                "records":records,
                "delivery":"PULL_ONLY_NOT_AUTOMATED",
                "cursor_contract":"Persist next_cursor only after successful processing; send on next call. No server-side read mark.",
                "model_calls_in_bridge":0,
            }
    except (sqlite3.Error,OSError) as e:
        return {"ok":False,"command":"scanner_candidates","error_type":type(e).__name__}

def scanner_health():
    """A bounded, verified snapshot of scanner runtime and provenance."""
    try:
        payload=_load_json(HEALTH_JSON.read_text(),{})
    except OSError as e:
        payload={"status":"health_file_missing","error_type":type(e).__name__}
    try:
        z=subprocess.run(["systemctl","--user","is-active","deepseek-market-scanner.service"],
                         capture_output=True,text=True,timeout=3,check=False)
        active=z.stdout.strip()=="active"
    except (OSError,subprocess.TimeoutExpired):
        active=False
    now=dt.datetime.now(dt.timezone.utc)
    reported_at=payload.get("at")
    lag=None
    if isinstance(reported_at,str):
        try:
            timepoint=dt.datetime.fromisoformat(reported_at.replace("Z","+00:00"))
            if timepoint.tzinfo: lag=max(0,int((now-timepoint).total_seconds()))
        except ValueError:pass
    try:
        with _connect() as db:
            counts=db.execute(
                "SELECT (SELECT COUNT(*) FROM candidates), "
                "(SELECT COALESCE(MAX(id),0) FROM candidates),"
                "(SELECT COUNT(*) FROM runs)").fetchone()
            last5=db.execute(
                "SELECT ts,session,universe_size,snapshots_received,signals_found,market_requests,"
                "model_requests FROM runs ORDER BY rowid DESC LIMIT 5").fetchall()
            latest_gaps=db.execute(
                "SELECT source,reason FROM gaps ORDER BY rowid DESC LIMIT 5").fetchall()
    except (sqlite3.Error,OSError):
        counts=(None,None,None)
        last5=[]
        latest_gaps=[]
    return {
        "ok":True,"command":"scanner_health",
        "service_active":active,
        "health":payload,
        "health_age_seconds":lag,
        "health_fresh":bool(active and lag is not None and lag<=180),
        "total_candidate_events":counts[0],
        "latest_candidate_id":counts[1],
        "completed_cycles":counts[2],
        "recent_cycles":[{
           "at":x[0],"session":x[1],"universe":x[2],
           "snapshots_received":x[3],"signal_records":x[4],
           "market_requests_since_start":x[5],"model_calls":x[6]
         } for x in last5],
        "recent_data_gaps":[{"source":x[0],"reason":x[1][:120]} for x in latest_gaps],
        "feed":"Alpaca IEX; not consolidated SIP",
        "bridge_model_calls":0,"bridge_broker_access":False,
    }

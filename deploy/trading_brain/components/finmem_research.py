"""FinMem-inspired offline research memory with point-in-time retrieval.

Independent research DB; NEVER opens the live controller's trading_state.db.
Decision evidence is immutable; outcomes are appended separately after they
become known. An evaluation query cannot see information from the future.
"""
from __future__ import annotations
from datetime import datetime, timezone
import sqlite3
from pathlib import Path

DDL = """
CREATE TABLE IF NOT EXISTS research_decision (
 decision_id TEXT PRIMARY KEY,
 ticker TEXT NOT NULL,
 observed_at_utc TEXT NOT NULL,
 phase TEXT NOT NULL,
 thesis TEXT NOT NULL,
 evidence_sha256 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS research_outcome (
 decision_id TEXT PRIMARY KEY,
 known_at_utc TEXT NOT NULL,
 label TEXT NOT NULL,
 observation TEXT NOT NULL,
 FOREIGN KEY(decision_id) REFERENCES research_decision(decision_id)
);
CREATE TABLE IF NOT EXISTS research_reflection (
 reflection_id TEXT PRIMARY KEY,
 decision_id TEXT NOT NULL,
 known_at_utc TEXT NOT NULL,
 lesson TEXT NOT NULL,
 FOREIGN KEY(decision_id) REFERENCES research_decision(decision_id)
);
"""

def _dt(value):
    if not isinstance(value,str):
        raise ValueError("timestamp required")
    stamp=datetime.fromisoformat(value.replace("Z","+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("timezone required")
    return stamp.astimezone(timezone.utc)

def connect(path):
    p=Path(path)
    p.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(str(p))
    db.row_factory=sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript(DDL)
    return db

def record_decision(db, *, decision_id, ticker, observed_at_utc, phase,
                    thesis, evidence_sha256):
    t=_dt(observed_at_utc).isoformat()
    if not all(isinstance(x,str) and x.strip()
               for x in (decision_id,ticker,phase,thesis,evidence_sha256)):
        raise ValueError("invalid decision fields")
    if len(evidence_sha256)!=64 or any(x not in "0123456789abcdef" for x in evidence_sha256):
        raise ValueError("invalid evidence SHA256")
    with db:
        db.execute(
            "INSERT INTO research_decision VALUES(?,?,?,?,?,?)",
            (decision_id,ticker.upper(),t,phase,thesis,evidence_sha256)
        )
    return decision_id

def add_outcome(db, *, decision_id, known_at_utc, label, observation):
    when=_dt(known_at_utc)
    r=db.execute("SELECT observed_at_utc FROM research_decision WHERE decision_id=?",
                 (decision_id,)).fetchone()
    if not r:raise ValueError("unknown decision")
    if when < _dt(r["observed_at_utc"]):
        raise ValueError("outcome predates decision")
    if not label or not observation:raise ValueError("outcome needs evidence")
    with db:
        db.execute("INSERT INTO research_outcome VALUES(?,?,?,?)",
                   (decision_id,when.isoformat(),label,observation))

def add_reflection(db, *, reflection_id, decision_id, known_at_utc, lesson):
    when=_dt(known_at_utc)
    prior=db.execute("SELECT observed_at_utc FROM research_decision WHERE decision_id=?",
                     (decision_id,)).fetchone()
    if not prior or when < _dt(prior["observed_at_utc"]):
        raise ValueError("unknown or future decision")
    if not reflection_id or not lesson:
        raise ValueError("reflection needs ID and lesson")
    with db:
        db.execute("INSERT INTO research_reflection VALUES(?,?,?,?)",
                   (reflection_id,decision_id,when.isoformat(),lesson))

def _tier(age_hours):
    if age_hours<24:return "short"
    if age_hours<14*24:return "medium"
    return "long"

def retrieve(db, *, as_of_utc, ticker=None, phase=None, limit=25):
    """Return ONLY information available by as_of; never silently insert outcomes."""
    cutoff=_dt(as_of_utc)
    if not isinstance(limit,int) or not 1<=limit<=100:
        raise ValueError("1..100 results required")
    query="SELECT * FROM research_decision WHERE observed_at_utc<=?"
    params=[cutoff.isoformat()]
    if ticker:
        query+=" AND ticker=?"
        params.append(ticker.upper())
    if phase:
        query+=" AND phase=?"
        params.append(phase)
    query+=" ORDER BY observed_at_utc DESC, decision_id ASC LIMIT ?"
    params.append(limit)
    out=[]
    for row in db.execute(query,params):
        observed=_dt(row["observed_at_utc"])
        hours=(cutoff-observed).total_seconds()/3600
        outcome=db.execute(
            "SELECT known_at_utc,label,observation FROM research_outcome "
            "WHERE decision_id=? AND known_at_utc<=?",
            (row["decision_id"],cutoff.isoformat())
        ).fetchone()
        reflections=db.execute(
            "SELECT reflection_id,known_at_utc,lesson FROM research_reflection "
            "WHERE decision_id=? AND known_at_utc<=? ORDER BY known_at_utc",
            (row["decision_id"],cutoff.isoformat())
        ).fetchall()
        out.append({
            "decision_id":row["decision_id"],"ticker":row["ticker"],
            "phase":row["phase"],"observed_at_utc":row["observed_at_utc"],
            "thesis":row["thesis"],"evidence_sha256":row["evidence_sha256"],
            "memory_tier":_tier(hours),
            "outcome":dict(outcome) if outcome else None,
            "reflections":[dict(x) for x in reflections],
        })
    return out

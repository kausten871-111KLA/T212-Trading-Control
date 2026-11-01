"""Seed a genuinely observed, point-in-time FinMem research journal.

Only source-backed historical research decisions are inserted. Outcomes/fills
are intentionally NOT invented. An empty assessed_at field in user-supplied
baseline is NOT replaced with a guessed time.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from finmem_research import connect, record_decision, retrieve

THIS = Path(__file__).resolve().parent
BENCH = THIS.parent / "benchmark"
sys.path.insert(0, str(BENCH))
from trading_brain_benchmark import fingerprint, observation_only, load_fixture

DATASET = BENCH / "alpaca_eod_20261020_20.json"
TRIAL = BENCH / "results/tradingagents_native_real_3symbols.json"
BASELINE = BENCH / "results/deepseek_baseline_validated_20261020.json"

def expected_seed_records():
    fixture = load_fixture(DATASET)
    evidence = observation_only(fixture)
    digest = fingerprint(evidence)
    trial = json.loads(TRIAL.read_text())
    baseline = json.loads(BASELINE.read_text())
    if not (trial.get("mocked") is False and trial.get("model_calls") == 9):
        raise ValueError("Source not genuine nine-call native model research")
    if trial.get("evidence_sha256") != digest or baseline.get("evidence_sha256") != digest:
        raise ValueError("Source fingerprint mismatch")
    if trial.get("dataset_id") != fixture["dataset_id"]:
        raise ValueError("Research dataset changed")
    instant = trial.get("assessed_at_utc")
    if not instant:
        raise ValueError("Authentic assessment timestamp missing")
    if baseline.get("assessed_at_utc"):
        raise ValueError("Unexpected baseline time: review and revise provenance policy")
    rows = trial.get("decisions")
    if not isinstance(rows, list) or len(rows) != 3:
        raise ValueError("Expected exactly three actual researched symbols")
    expected_symbols = ("BRZE", "MYGN", "PRSO")
    if tuple(x.get("ticker") for x in rows) != expected_symbols:
        raise ValueError("Unexpected native research symbol set")
    out = []
    for x in rows:
        ticker = x["ticker"]
        action = x.get("action")
        explanation = x.get("thesis")
        if action not in ("BUY", "SELL", "HOLD", "WAIT", "RESEARCH"):
            raise ValueError("Unrecognised research recommendation")
        if not isinstance(explanation, str) or not explanation.strip():
            raise ValueError("Original model thesis absent")
        out.append({
            "decision_id": "native-nine-call-20261020-" + ticker,
            "ticker": ticker,
            "observed_at_utc": instant,
            "phase": "TradingAgents Native RESEARCH, not broker execution",
            "thesis": ("PROPOSED RESEARCH ACTION " + action +
                      "; NOT AN ORDER, NOT A FILL, NOT AN OUTCOME. " +
                      "Source: actual TradingAgents v0.7.0 native bull/bear/trader "
                      "DeepSeek OpenRouter trial. Original thesis: " + explanation),
            "evidence_sha256": digest,
        })
    return out

def seed(destination: Path):
    rows = expected_seed_records()
    conn = connect(destination)
    created = 0
    try:
        prior_outcomes = conn.execute("SELECT COUNT(*) FROM research_outcome").fetchone()[0]
        prior_reflections = conn.execute("SELECT COUNT(*) FROM research_reflection").fetchone()[0]
        for row in rows:
            existing = conn.execute(
                "SELECT decision_id,ticker,observed_at_utc,phase,thesis,evidence_sha256 "
                "FROM research_decision WHERE decision_id=?",
                (row["decision_id"],),
            ).fetchone()
            if existing:
                if dict(existing) != row:
                    raise ValueError("Existing decision differs; refuse overwrite")
                continue
            record_decision(conn, **row)
            created += 1
        assert conn.execute("SELECT COUNT(*) FROM research_outcome").fetchone()[0] == prior_outcomes, \
            "Seeding must never create or alter historical outcomes"
        assert conn.execute("SELECT COUNT(*) FROM research_reflection").fetchone()[0] == prior_reflections, \
            "Seeding must never invent retrospective reflections"
        visible = retrieve(conn, as_of_utc="2026-10-22T08:00:00Z", ticker="MYGN")
        if len(visible) != 1 or visible[0]["decision_id"] != "native-nine-call-20261020-MYGN":
            raise ValueError("Research retrieval or provenance corrupted")
        if prior_outcomes == 0 and visible[0]["outcome"] is not None:
            raise ValueError("Research journal gained an invented outcome")
        digest = rows[0]["evidence_sha256"]
        return {"created": created, "total_seeded": len(rows),
                "original_source": "TradingAgents real nine-call research",
                "sha256_evidence": digest,
                "broker_orders": 0, "outcomes_added": 0,
                "baseline_without_assessment_timestamp_imported": False,
                "journal_path": str(destination)}
    finally:
        conn.close()

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: seed_finmem_from_research.py OUTPUT_SQLITE_PATH")
    report = seed(Path(sys.argv[1]))
    print("FINMEM_RESEARCH_SOURCE_SEED_PASS",
          "created", report["created"],
          "total", report["total_seeded"],
          "broker_orders", report["broker_orders"],
          "outcomes", report["outcomes_added"])

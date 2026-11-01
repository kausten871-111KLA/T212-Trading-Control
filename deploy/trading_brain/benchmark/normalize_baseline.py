"""Preserve original DeepSeek output while producing a strict-comparison copy."""
from collections import Counter
from copy import deepcopy
import argparse
import json
from pathlib import Path
from trading_brain_benchmark import fingerprint, load_fixture, observation_only, validate_decisions

def normalize(source: Path, fixture: Path):
    evidence=observation_only(load_fixture(fixture))
    original=json.loads(source.read_text(encoding="utf-8"))
    assert original["dataset_id"]==evidence["dataset_id"]
    assert original["evidence_sha256"]==fingerprint(evidence)
    rows=original["decisions"]
    assert len(rows)==len(evidence["candidates"])==20
    known={r["ticker"] for r in evidence["candidates"]}
    names=[r["ticker"] for r in rows]
    assert set(names)==known and len(set(names))==len(names)
    norm=deepcopy(original)
    outside=[]
    for row in norm["decisions"]:
        external=sorted(set(row["evidence_tickers"])-known)
        if external:
            outside.append({"ticker":row["ticker"],"unsupported_references":external})
            row["evidence_tickers"]=[x for x in row["evidence_tickers"] if x in known]
            for symbol in external:
                row["missing_evidence"].append(
                    f"External symbol {symbol}: not in the frozen 20-symbol evidence; cannot be used as verified support"
                )
    report={
        "source":"DeepSeek baseline from user-uploaded response; exact original preserved",
        "dataset_id":evidence["dataset_id"],
        "evidence_sha256":fingerprint(evidence),
        "original_decisions":len(rows),
        "actions":dict(Counter(x["action"] for x in rows)),
        "unsupported_ticker_references":outside,
        "unsupported_reference_occurrences":sum(len(x["unsupported_references"]) for x in outside),
        "normalization_scope":"Only invalid evidence_tickers removed and missing_evidence annotated. No action, thesis, bull or bear text changed.",
        "verification_limitations":[
            "No independent vendor raw response or quote timestamp for these snapshot rows",
            "Unverified takeover/IPO/catalyst descriptions are hypotheses, not checked news",
            "Some narrative claims rely on previous memory or facts outside frozen evidence",
            "No P&L or trade-execution outcome established by this EOD comparison",
        ],
    }
    return norm,report

def main():
    p=argparse.ArgumentParser()
    p.add_argument("fixture",type=Path)
    p.add_argument("original",type=Path)
    p.add_argument("--normalized",required=True,type=Path)
    p.add_argument("--report",required=True,type=Path)
    a=p.parse_args()
    normalized,report=normalize(a.original,a.fixture)
    a.normalized.write_text(json.dumps(normalized,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    a.report.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    validate_decisions(a.normalized,observation_only(load_fixture(a.fixture)))
    print("BASELINE_NORMALIZATION_PASS",json.dumps({
        "decisions":len(normalized["decisions"]),
        "actions":report["actions"],
        "unsupported_references":report["unsupported_reference_occurrences"],
        "sha256":report["evidence_sha256"],
    },sort_keys=True))

if __name__=="__main__":
    main()

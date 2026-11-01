"""Generate an audit-only research report; never touches production services."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import tempfile
from offline_replay import replay

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--as-of",default="2026-10-21T08:00:00Z")
    args=p.parse_args()
    folder=Path(__file__).resolve().parent.parent/"benchmark"
    with tempfile.TemporaryDirectory(prefix="trading-brain-lab-") as tmp:
        result=replay(folder/"alpaca_eod_20261020_20.json",
                      folder/"results/deepseek_baseline_validated_20261020.json",
                      folder/"results/tradingagents_native_real_3symbols.json",
                      sqlite_path=Path(tmp)/"research.sqlite3",
                      as_of_utc=args.as_of)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print("TRADING_BRAIN_OFFLINE_REPLAY_PASS",
          "symbols",len(result["rows"]),
          "memory_entries",result["memory_decisions_visible_as_of"],
          "model_calls",result["model_calls_this_replay"],
          "broker_orders",result["broker_orders_this_replay"])

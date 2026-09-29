"""
title: Opportunity Ledger
author: Katie / OpenAI
description: Persistent JSONL state ledger for scanner candidates and audit events. No broker writes.
version: 0.1.0
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


class OpportunityLedger:
    def __init__(self, path: str = "/app/backend/data/trading_opportunity_ledger.jsonl"):
        self.path = Path(path)

    def append(self, event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        event = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "payload": payload,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, default=str) + "\n")
        return event

    def read_recent(self, limit: int = 500) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        rows: List[Dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
        return rows[-max(1, int(limit)):]

    def latest_for_symbol(self, symbol: str) -> Optional[Dict[str, Any]]:
        symbol = (symbol or "").upper()
        for event in reversed(self.read_recent(5000)):
            payload = event.get("payload") or {}
            event_symbol = str(
                payload.get("symbol")
                or payload.get("ticker")
                or payload.get("t212_ticker")
                or ""
            ).upper()
            if event_symbol == symbol:
                return event
        return None

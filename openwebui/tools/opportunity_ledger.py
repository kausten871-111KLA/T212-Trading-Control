"""
title: Opportunity Ledger
author: Katie / OpenAI
description: Persistent JSONL state ledger for scanner candidates and audit events. No broker writes.
version: 0.1.0
"""

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


class OpportunityLedger:
    def __init__(self, path: str = "/app/backend/data/trading_opportunity_ledger.jsonl"):
        self.path = Path(path)

    def append(self, event_type: str, payload: Dict[str, Any], *, event_id: str | None = None, correlation_id: str | None = None) -> Dict[str, Any]:
        import fcntl
        if not isinstance(event_type, str) or not event_type.strip():
            raise ValueError("Nonempty event_type required")
        if not isinstance(payload, dict):
            raise ValueError("Event payload must be a dictionary")
        if correlation_id is None:
            correlation_id = payload.get("scan_id")
        event_id = str(uuid.uuid4()) if event_id is None else event_id
        if not isinstance(event_id, str) or not event_id.strip():
            raise ValueError("Nonempty event_id required")
        if correlation_id is not None and (not isinstance(correlation_id, str) or not correlation_id.strip()):
            raise ValueError("Nonempty correlation_id required when supplied")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        event = {
            "event_id": event_id,
            "correlation_id": correlation_id,
            "ts": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "payload": payload,
        }
        encoded = json.dumps(event, default=str, allow_nan=False) + "\n"
        fd = os.open(self.path, os.O_APPEND | os.O_CREAT | os.O_WRONLY | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o600)
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
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


"""
title: Catalyst Handoff Queue
author: Katie / OpenAI
description: Persistent JSONL queue for newly-qualified or newly-escalated scanner candidates. No broker writes.
version: 0.1.0
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


class CatalystHandoffQueue:
    def __init__(self, path: str = "/app/backend/data/catalyst_handoff_queue.jsonl"):
        self.path = Path(path)

    def enqueue(self, candidate: Dict[str, Any]) -> Dict[str, Any]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        event = {
            "queued_at": datetime.now(timezone.utc).isoformat(),
            "status": "pending",
            "candidate": candidate,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, default=str) + "\n")
        return event

    def pending(self, limit: int = 20) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        rows = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    event = json.loads(line)
                except Exception:
                    continue
                if event.get("status") == "pending":
                    rows.append(event)
        return rows[: max(1, int(limit))]

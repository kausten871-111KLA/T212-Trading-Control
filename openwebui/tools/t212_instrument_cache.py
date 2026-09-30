"""
title: T212 Instrument Cache
author: Katie / OpenAI
description: Read-only helper for caching Trading 212 DEMO instrument metadata and producing daily diffs.
version: 0.1.0
"""

import json
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List

try:
    import fcntl
except ImportError:
    fcntl = None


class InstrumentCache:
    def __init__(
        self,
        cache_path: str = "/app/backend/data/t212_instrument_cache.json",
        diff_path: str = "/app/backend/data/t212_instrument_diff.json",
        ttl_seconds: int = 86400,
    ):
        self.cache_path = Path(cache_path)
        self.diff_path = Path(diff_path)
        self.ttl_seconds = int(ttl_seconds)
        self.lock_path = self.cache_path.with_suffix(self.cache_path.suffix + ".lock")

    @contextmanager
    def lock(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.lock_path.open("a+")
        try:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()

    def load(self) -> Dict[str, Any] | None:
        if not self.cache_path.exists():
            return None
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and isinstance(payload.get("instruments"), list):
                return payload
        except Exception:
            return None
        return None

    def is_fresh(self, payload: Dict[str, Any] | None) -> bool:
        if not payload:
            return False
        try:
            fetched_at = float(payload.get("fetchedAtEpoch", 0))
            return (time.time() - fetched_at) < self.ttl_seconds
        except Exception:
            return False

    def _write_json_atomic(self, path: Path, payload: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        temp.replace(path)

    def diff(
        self,
        previous: List[Dict[str, Any]],
        current: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        prev = {str(x.get("ticker")): x for x in previous if x.get("ticker")}
        cur = {str(x.get("ticker")): x for x in current if x.get("ticker")}

        added = [cur[t] for t in sorted(set(cur) - set(prev))]
        removed = [prev[t] for t in sorted(set(prev) - set(cur))]

        tracked = (
            "name",
            "shortName",
            "isin",
            "currencyCode",
            "type",
            "extendedHours",
            "maxOpenQuantity",
        )
        changed = []
        for ticker in sorted(set(prev) & set(cur)):
            changes = {
                field: {"before": prev[ticker].get(field), "after": cur[ticker].get(field)}
                for field in tracked
                if prev[ticker].get(field) != cur[ticker].get(field)
            }
            if changes:
                changed.append({"ticker": ticker, "changes": changes})

        return {
            "generatedAtEpoch": time.time(),
            "baselineWasPresent": bool(previous),
            "addedCount": len(added),
            "removedCount": len(removed),
            "changedCount": len(changed),
            "added": added,
            "removed": removed,
            "changed": changed,
        }

    def save_snapshot(
        self,
        instruments: List[Dict[str, Any]],
        previous: List[Dict[str, Any]] | None = None,
    ) -> Dict[str, Any]:
        previous = previous or []
        now = time.time()
        payload = {
            "provider": "Trading212",
            "environment": "DEMO",
            "fetchedAtEpoch": now,
            "count": len(instruments),
            "instruments": instruments,
        }
        diff_payload = self.diff(previous, instruments)
        if not previous:
            diff_payload["added"] = []
            diff_payload["addedCount"] = 0
        self._write_json_atomic(self.cache_path, payload)
        self._write_json_atomic(self.diff_path, diff_payload)
        return diff_payload

    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        payload = self.load()
        if not payload:
            return []
        needle = (query or "").strip().lower()
        if not needle:
            return []

        rows = []
        for inst in payload.get("instruments", []):
            haystack = " ".join(
                str(inst.get(k, ""))
                for k in ("ticker", "name", "shortName", "isin")
            ).lower()
            if needle in haystack:
                rows.append(inst)
                if len(rows) >= max(1, int(limit)):
                    break
        return rows

    def latest_diff(self) -> Dict[str, Any]:
        if not self.diff_path.exists():
            return {}
        try:
            return json.loads(self.diff_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

"""
title: Movement Tier State
author: Katie / OpenAI
description: Deterministic movement-tier escalation tracker for opportunity discovery. No broker writes and no LLM calls.
version: 0.1.0
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional


class MovementTierState:
    def __init__(self, path: str = "/app/backend/data/trading_movement_tiers.json", tiers: Optional[List[float]] = None):
        self.path = Path(path)
        self.tiers = tiers or [5.0, 10.0, 20.0, 50.0, 100.0]

    def _load(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save(self, payload: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        temp.replace(self.path)

    def tier_for_change(self, change_pct: float) -> float:
        reached = 0.0
        for tier in self.tiers:
            if change_pct >= tier:
                reached = tier
        return reached

    def update(self, symbol: str, change_pct: float) -> Dict[str, Any]:
        symbol = (symbol or "").upper().strip()
        if not symbol:
            return {"error": "empty symbol"}

        state = self._load()
        previous = state.get(symbol) or {}
        previous_tier = float(previous.get("tier", 0.0) or 0.0)
        current_tier = self.tier_for_change(float(change_pct))
        escalated = current_tier > previous_tier

        state[symbol] = {
            "tier": current_tier,
            "last_change_pct": float(change_pct),
        }
        self._save(state)

        return {
            "symbol": symbol,
            "previous_tier": previous_tier,
            "current_tier": current_tier,
            "escalated": escalated,
            "newly_qualified": previous_tier == 0.0 and current_tier > 0.0,
        }

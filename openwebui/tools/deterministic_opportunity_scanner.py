"""
title: Deterministic Opportunity Scanner Core
author: Katie / OpenAI
description: Pure deterministic ranking/gating core for DEMO market discovery. No broker writes and no LLM calls.
version: 0.2.0
"""

from dataclasses import dataclass, asdict
from typing import Any, Dict, Iterable, List, Optional


@dataclass
class ScannerConfig:
    move_min_pct: float = 5.0
    rel_vol_min: float = 2.0
    spread_exec_max_pct: float = 2.5
    spread_watch_max_pct: float = 5.0
    price_min: float = 0.50
    today_dollar_vol_min: float = 500_000.0
    shortlist_top_m: int = 20
    reject_symbol_suffixes: tuple = (".W", ".WS", ".WT", ".RT", ".R", ".U")


class DeterministicScanner:
    def __init__(self, config: Optional[ScannerConfig] = None):
        self.config = config or ScannerConfig()

    def _safe_float(self, value, default=None):
        try:
            return float(value)
        except Exception:
            return default

    def _gate(self, row: Dict[str, Any]) -> Dict[str, Any]:
        cfg = self.config
        price = self._safe_float(row.get("price"))
        change = self._safe_float(row.get("change_pct"))
        rel_vol = self._safe_float(row.get("rel_vol"))
        spread = self._safe_float(row.get("spread_pct"))
        dollar_vol = self._safe_float(row.get("dollar_vol"))
        tradable = bool(row.get("tradable"))
        symbol = str(row.get("symbol") or "").upper().strip()
        asset_status = str(row.get("asset_status") or "").lower().strip()

        reasons = []
        if any(symbol.endswith(suffix) for suffix in cfg.reject_symbol_suffixes):
            reasons.append("SECURITY_TYPE")
        if asset_status in {"inactive", "delisted", "legacy", "stale"}:
            reasons.append("ASSET_STATUS")
        state = "qualified"

        if price is None or price < cfg.price_min:
            reasons.append("PRICE")
        if change is None or change < cfg.move_min_pct:
            reasons.append("MOVE")
        if rel_vol is None or rel_vol < cfg.rel_vol_min:
            reasons.append("VOLUME")
        if not tradable:
            reasons.append("T212")
        if dollar_vol is None or dollar_vol < cfg.today_dollar_vol_min:
            reasons.append("LIQUIDITY")

        if spread is None:
            reasons.append("SPREAD_UNKNOWN")
        elif spread > cfg.spread_watch_max_pct:
            reasons.append("SPREAD")
        elif spread > cfg.spread_exec_max_pct:
            state = "watch-illiquid"

        if reasons:
            state = "rejected"

        return {
            **row,
            "scanner_state": state,
            "gate_failures": reasons,
        }

    def _rank_score(self, row: Dict[str, Any]) -> float:
        change = max(self._safe_float(row.get("change_pct"), 0.0), 0.0)
        rel_vol = max(self._safe_float(row.get("rel_vol"), 0.0), 0.0)
        spread = max(self._safe_float(row.get("spread_pct"), 100.0), 0.0)
        dollar_vol = max(self._safe_float(row.get("dollar_vol"), 0.0), 0.0)

        change_score = min(change / 50.0, 1.0)
        volume_score = min(rel_vol / 10.0, 1.0)
        liquidity_score = min(dollar_vol / 10_000_000.0, 1.0)
        spread_score = max(0.0, 1.0 - min(spread / 5.0, 1.0))

        return round(
            0.4 * change_score
            + 0.3 * volume_score
            + 0.2 * liquidity_score
            + 0.1 * spread_score,
            6,
        )

    def scan(self, rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
        evaluated: List[Dict[str, Any]] = []
        for row in rows:
            gated = self._gate(dict(row))
            gated["rank_score"] = self._rank_score(gated)
            evaluated.append(gated)

        qualified = [
            row for row in evaluated
            if row.get("scanner_state") in ("qualified", "watch-illiquid")
        ]
        qualified.sort(key=lambda item: item.get("rank_score", 0.0), reverse=True)

        return {
            "scannerVersion": "0.2.0",
            "config": asdict(self.config),
            "evaluatedCount": len(evaluated),
            "qualifiedCount": len(qualified),
            "shortlist": qualified[: self.config.shortlist_top_m],
            "rejected": [
                row for row in evaluated if row.get("scanner_state") == "rejected"
            ],
            "note": "Deterministic discovery only. No order placement and no LLM calls.",
        }

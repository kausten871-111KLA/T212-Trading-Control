"""
title: Missed Green Audit Core
author: Katie / OpenAI
description: Deterministic EOD audit comparing actual movers, scanner surfacing, and broker fills. No order placement.
version: 0.1.0
"""

from typing import Any, Dict, Iterable, List


class MissedGreenAudit:
    def __init__(self, top_n: int = 100):
        self.top_n = max(1, int(top_n))

    def _key(self, row: Dict[str, Any]) -> str:
        return str(
            row.get("t212_ticker")
            or row.get("symbol")
            or row.get("ticker")
            or ""
        ).upper()

    def classify(
        self,
        actual_movers: Iterable[Dict[str, Any]],
        surfaced: Iterable[Dict[str, Any]],
        traded: Iterable[Dict[str, Any]],
    ) -> Dict[str, Any]:
        actual = list(actual_movers)[: self.top_n]
        surfaced_map = {self._key(x): x for x in surfaced if self._key(x)}
        traded_map = {self._key(x): x for x in traded if self._key(x)}

        rows: List[Dict[str, Any]] = []

        for mover in actual:
            key = self._key(mover)
            surfaced_row = surfaced_map.get(key)
            traded_row = traded_map.get(key)

            if not surfaced_row:
                code = "NEV"
                reason = "never surfaced"
            elif traded_row:
                code = "TRADED"
                reason = "broker-confirmed trade exists"
            elif surfaced_row.get("scanner_state") == "rejected":
                code = "RET"
                reason = "surfaced but rejected by deterministic gate"
            elif surfaced_row.get("catalyst_state") in ("unknown", "unverified", "none"):
                code = "AVOIDED"
                reason = "surfaced but no verified catalyst"
            else:
                code = "NOTRADED"
                reason = "surfaced and qualified but not traded"

            rows.append({
                "symbol": mover.get("symbol") or mover.get("ticker"),
                "t212_ticker": mover.get("t212_ticker"),
                "change_pct": mover.get("change_pct") or mover.get("changePctVsPrevClose"),
                "audit_code": code,
                "audit_reason": reason,
                "scanner_state": (surfaced_row or {}).get("scanner_state"),
                "gate_failures": (surfaced_row or {}).get("gate_failures"),
                "catalyst_state": (surfaced_row or {}).get("catalyst_state"),
                "traded": bool(traded_row),
            })

        counts = {}
        for row in rows:
            counts[row["audit_code"]] = counts.get(row["audit_code"], 0) + 1

        return {
            "auditVersion": "0.1.0",
            "topN": self.top_n,
            "counts": counts,
            "rows": rows,
            "note": (
                "Deterministic audit only. Threshold changes are recommendations only "
                "and must never be auto-applied."
            ),
        }

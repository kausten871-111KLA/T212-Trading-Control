"""
title: Opportunity Scan Pipeline
author: Katie / OpenAI
description: Deterministic pipeline that enriches Alpaca snapshots, checks T212 tradability, ranks candidates, and persists scan events. No broker writes and no LLM calls.
version: 0.1.0
"""

from typing import Any, Dict, Iterable, List

from deterministic_opportunity_scanner import DeterministicScanner, ScannerConfig
from opportunity_ledger import OpportunityLedger
from scanner_metrics import enrich_snapshot


class OpportunityScanPipeline:
    def __init__(self, scanner=None, ledger=None):
        self.scanner = scanner or DeterministicScanner(ScannerConfig())
        self.ledger = ledger or OpportunityLedger()

    def build_rows(self, snapshots: Iterable[Dict[str, Any]], avg20_volume_by_symbol: Dict[str, float], t212_lookup: Dict[str, str]) -> List[Dict[str, Any]]:
        rows = []
        for snapshot in snapshots:
            symbol = str(snapshot.get("symbol") or "").upper()
            if not symbol:
                continue
            t212_ticker = t212_lookup.get(symbol)
            rows.append(enrich_snapshot(
                snapshot=snapshot,
                avg20_volume=avg20_volume_by_symbol.get(symbol),
                t212_ticker=t212_ticker,
                tradable=bool(t212_ticker),
            ))
        return rows

    def run(self, snapshots, avg20_volume_by_symbol, t212_lookup):
        rows = self.build_rows(snapshots, avg20_volume_by_symbol, t212_lookup)
        result = self.scanner.scan(rows)
        for row in result.get("shortlist", []):
            self.ledger.append("scanner_shortlist", row)
        for row in result.get("rejected", []):
            self.ledger.append("scanner_rejected", row)
        return result

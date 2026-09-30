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
from movement_tier_state import MovementTierState
from catalyst_handoff_queue import CatalystHandoffQueue


class OpportunityScanPipeline:
    def __init__(self, scanner=None, ledger=None, tier_state=None, catalyst_queue=None):
        self.scanner = scanner or DeterministicScanner(ScannerConfig())
        self.ledger = ledger or OpportunityLedger()
        self.tier_state = tier_state or MovementTierState()
        self.catalyst_queue = catalyst_queue or CatalystHandoffQueue()

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
        queued = []
        for row in result.get("shortlist", []):
            self.ledger.append("scanner_shortlist", row)
            symbol = str(row.get("symbol") or "").upper()
            change_pct = float(row.get("change_pct") or 0.0)
            tier = self.tier_state.update(symbol, change_pct)
            row["tier_state"] = tier
            if tier.get("newly_qualified") or tier.get("escalated"):
                event = self.catalyst_queue.enqueue(row)
                if event.get("queued"):
                    self.ledger.append("catalyst_handoff_queued", event)
                    queued.append(event)
                else:
                    self.ledger.append("catalyst_handoff_skipped", {
                        "symbol": symbol,
                        "reason": event.get("reason"),
                        "tier_state": tier,
                    })
        for row in result.get("rejected", []):
            self.ledger.append("scanner_rejected", row)
        result["catalystQueueCount"] = len(queued)
        result["catalystQueueEvents"] = queued
        result["catalystQueueStats"] = self.catalyst_queue.stats()
        return result

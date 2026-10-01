#!/usr/bin/env python3
"""Bounded deterministic T212 DEMO discovery cycle.

No broker-write path exists in this worker. It consumes fresh market data,
requires a fresh DEMO instrument cache, runs deterministic qualification,
persists evidence, and queues candidates for catalyst review.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from openwebui.tools.automation_ledger import append_run
from openwebui.tools.catalyst_handoff_queue import CatalystHandoffQueue
from openwebui.tools.deterministic_opportunity_scanner import DeterministicScanner
from openwebui.tools.movement_tier_state import MovementTierState
from openwebui.tools.opportunity_ledger import OpportunityLedger
from worker.discovery_adapter import (
    DiscoveryInputError,
    load_instrument_cache,
    load_snapshot,
    normalize_rows,
)


STATE = Path(os.getenv("T212_SCANNER_STATE_DIR", "/var/lib/t212-scanner"))
STATUS_PATH = Path(os.getenv("TRADING_WORKER_STATUS", str(STATE / "status.json")))
LOG_PATH = Path(os.getenv("TRADING_WORKER_LOG", str(STATE / "worker.jsonl")))
SNAPSHOT_PATH = Path(os.getenv("T212_MARKET_SNAPSHOT", str(STATE / "market_snapshot.json")))
CACHE_PATH = Path(os.getenv("T212_INSTRUMENT_CACHE", str(STATE / "t212_instrument_cache.json")))
SCAN_OUT = Path(os.getenv("T212_SCAN_OUTPUT", str(STATE / "scanner_latest.json")))
SURFACED_OUT = Path(os.getenv("T212_SURFACED_OUTPUT", str(STATE / "surfaced_candidates.json")))
AUTOMATION_LEDGER = Path(os.getenv("T212_AUTOMATION_LEDGER", str(STATE / "automation_runs.jsonl")))
SNAPSHOT_MAX_AGE_SECONDS = int(os.getenv("T212_MARKET_MAX_AGE_SECONDS", "300"))
CACHE_TTL_SECONDS = int(os.getenv("T212_INSTRUMENT_CACHE_TTL_SECONDS", "86400"))


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def log(event: str, payload: dict | None = None) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "payload": payload or {},
    }
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, default=str) + "\n")


def ledger_record(
    *,
    run_id: str,
    started_at: str,
    status: str,
    ended_at: str,
    evidence: list[str],
    output_refs: list[str],
    next_action: str,
    error: str | None = None,
) -> dict:
    return {
        "run_id": run_id,
        "workspace": "t212-demo",
        "workflow": "deterministic-market-discovery",
        "started_at": started_at,
        "ended_at": ended_at,
        "heartbeat_at": ended_at,
        "status": status,
        "attempt": 1,
        "input_refs": [SNAPSHOT_PATH.name, CACHE_PATH.name],
        "output_refs": output_refs,
        "evidence": evidence,
        "model_role": None,
        "tool_ids": [],
        "cost": {"currency": "NONE", "estimated": 0, "actual": 0},
        "error": error,
        "approvals": [{"action": "discovery_read_only", "state": "NOT_REQUIRED"}],
        "next_action": next_action,
        "safety": {
            "environment": "DEMO",
            "live_trading": False,
            "order_mutation": False,
        },
    }


def run_cycle() -> dict:
    snapshot = load_snapshot(
        SNAPSHOT_PATH,
        max_age_seconds=SNAPSHOT_MAX_AGE_SECONDS,
    )
    cache = load_instrument_cache(
        CACHE_PATH,
        ttl_seconds=CACHE_TTL_SECONDS,
    )
    rows = normalize_rows(snapshot["rows"], cache["instruments"])
    if not rows:
        raise DiscoveryInputError("market snapshot contained no usable symbol rows")

    scanner = DeterministicScanner()
    result = scanner.scan(rows)

    tiers = MovementTierState(path=str(STATE / "movement_tiers.json"))
    queue = CatalystHandoffQueue(path=str(STATE / "catalyst_handoff_queue.jsonl"), max_per_day=20)
    opportunity_ledger = OpportunityLedger(path=str(STATE / "trading_opportunity_ledger.jsonl"))

    surfaced = []
    queued_count = 0
    for candidate in result["shortlist"]:
        tier_state = tiers.update(candidate.get("symbol"), candidate.get("change_pct") or 0)
        candidate = {**candidate, "tier_state": tier_state}
        surfaced.append(candidate)
        opportunity_ledger.append("scanner_shortlist", candidate)
        if tier_state.get("current_tier", 0) > 0:
            queued = queue.enqueue(candidate)
            if queued.get("queued"):
                queued_count += 1

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "environment": "DEMO",
        "source": snapshot["source"],
        "source_age_seconds": snapshot["age_seconds"],
        "instrument_cache_age_seconds": cache["age_seconds"],
        "evaluated_count": result["evaluatedCount"],
        "qualified_count": result["qualifiedCount"],
        "shortlist_count": len(surfaced),
        "catalyst_queued_count": queued_count,
        "shortlist": surfaced,
        "rejected": result["rejected"],
        "orders_submitted": 0,
        "live_trading_enabled": False,
        "order_mutation_enabled": False,
    }
    atomic_json(SCAN_OUT, output)
    atomic_json(SURFACED_OUT, surfaced)
    return output


def main() -> int:
    started = datetime.now(timezone.utc)
    run_id = f"discovery-{started.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    status = {
        "run_id": run_id,
        "started_at": started.isoformat(),
        "mode": "DEMO",
        "ok": False,
        "live_trading_enabled": False,
        "orders_submitted": 0,
    }
    try:
        output = run_cycle()
        ended = datetime.now(timezone.utc).isoformat()
        status.update(
            {
                "ok": True,
                "finished_at": ended,
                "message": "deterministic discovery completed",
                "source": output["source"],
                "source_age_seconds": output["source_age_seconds"],
                "instrument_cache_age_seconds": output["instrument_cache_age_seconds"],
                "evaluated_count": output["evaluated_count"],
                "qualified_count": output["qualified_count"],
                "shortlist_count": output["shortlist_count"],
                "catalyst_queued_count": output["catalyst_queued_count"],
            }
        )
        atomic_json(STATUS_PATH, status)
        log("discovery_succeeded", status)
        append_run(
            AUTOMATION_LEDGER,
            ledger_record(
                run_id=run_id,
                started_at=started.isoformat(),
                status="SUCCEEDED",
                ended_at=ended,
                evidence=[
                    f"source_age_seconds={output['source_age_seconds']}",
                    f"instrument_cache_age_seconds={output['instrument_cache_age_seconds']}",
                    f"evaluated_count={output['evaluated_count']}",
                    f"qualified_count={output['qualified_count']}",
                    "orders_submitted=0",
                ],
                output_refs=[SCAN_OUT.name, SURFACED_OUT.name],
                next_action="catalyst verification for queued candidates",
            ),
        )
        print(json.dumps(status, sort_keys=True))
        return 0

    except DiscoveryInputError as exc:
        ended = datetime.now(timezone.utc).isoformat()
        message = str(exc)
        status.update(
            {
                "finished_at": ended,
                "blocked": True,
                "message": message,
            }
        )
        atomic_json(STATUS_PATH, status)
        log("discovery_blocked", status)
        append_run(
            AUTOMATION_LEDGER,
            ledger_record(
                run_id=run_id,
                started_at=started.isoformat(),
                status="BLOCKED",
                ended_at=ended,
                evidence=[message, "orders_submitted=0"],
                output_refs=[STATUS_PATH.name],
                next_action="restore fresh market snapshot and DEMO instrument cache",
                error=message,
            ),
        )
        print(json.dumps(status, sort_keys=True))
        return 2

    except Exception as exc:
        ended = datetime.now(timezone.utc).isoformat()
        message = f"{type(exc).__name__}: {exc}"
        status.update(
            {
                "finished_at": ended,
                "error": message,
            }
        )
        atomic_json(STATUS_PATH, status)
        log(
            "discovery_failed",
            {
                **status,
                "traceback": traceback.format_exc(),
            },
        )
        try:
            append_run(
                AUTOMATION_LEDGER,
                ledger_record(
                    run_id=run_id,
                    started_at=started.isoformat(),
                    status="FAILED",
                    ended_at=ended,
                    evidence=["orders_submitted=0"],
                    output_refs=[STATUS_PATH.name],
                    next_action="inspect worker error and rerun after fix",
                    error=message,
                ),
            )
        except Exception:
            pass
        print(json.dumps(status, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

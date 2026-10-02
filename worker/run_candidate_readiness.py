#!/usr/bin/env python3
"""Build fail-closed candidate readiness from catalyst and fresh broker evidence.

The worker performs no broker writes. A broker read is attempted only when a
candidate has already passed deterministic scanner and catalyst gates.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from openwebui.tools.catalyst_handoff_queue import CatalystHandoffQueue
from worker.session_gate import evaluate_session


STATE = Path(os.getenv("T212_SCANNER_STATE_DIR", "/var/lib/t212-scanner"))
QUEUE_PATH = Path(os.getenv("T212_CATALYST_QUEUE", str(STATE / "catalyst_handoff_queue.jsonl")))
OUT_PATH = Path(os.getenv("T212_READINESS_OUTPUT", str(STATE / "candidate_readiness.json")))
BROKER_PATH = Path(os.getenv("T212_BROKER_SNAPSHOT", str(STATE / "broker_snapshot.json")))
MAX_REVIEWS = min(5, max(1, int(os.getenv("T212_READINESS_MAX_REVIEWS", "5"))))
BROKER_MAX_AGE_SECONDS = max(30, int(os.getenv("T212_BROKER_MAX_AGE_SECONDS", "120")))


class ReadinessError(RuntimeError):
    pass


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(path)


def _number(value: Any, field: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ReadinessError(f"broker {field} is missing or non-numeric") from exc


def normalize_broker_dashboard(raw: Any, *, observed_at: datetime) -> dict[str, Any]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError as exc:
            raise ReadinessError("broker dashboard did not return JSON") from exc
    if not isinstance(raw, dict):
        raise ReadinessError("broker dashboard must be an object")
    if raw.get("environment") != "DEMO" or raw.get("liveTradingEnabled") is not False:
        raise ReadinessError("broker dashboard is not DEMO with LIVE disabled")
    account = raw.get("account")
    positions = raw.get("positions")
    orders = raw.get("pendingOrders")
    if not isinstance(account, dict) or not isinstance(positions, list) or not isinstance(orders, list):
        raise ReadinessError("broker dashboard lacks account, positions or pending orders")
    cash = account.get("cash") if isinstance(account.get("cash"), dict) else {}
    equity = _number(account.get("totalValue", account.get("total")), "equity")
    available_cash = _number(cash.get("availableToTrade", account.get("availableCash")), "available cash")
    currency = str(account.get("currency") or account.get("currencyCode") or "GBP").upper()
    if equity <= 0 or available_cash < 0:
        raise ReadinessError("broker equity/cash values are invalid")
    if currency != "GBP":
        raise ReadinessError("broker account currency is not GBP")
    return {
        "generated_at": observed_at.astimezone(timezone.utc).isoformat(),
        "environment": "DEMO",
        "live_trading_enabled": False,
        "broker_verified": True,
        "gateway_version": raw.get("gatewayVersion"),
        "currency": currency,
        "equity": equity,
        "available_cash": available_cash,
        "open_position_count": len(positions),
        "pending_order_count": len(orders),
        "positions": positions,
        "pending_orders": orders,
        "orders_submitted": 0,
    }


def candidate_gate(event: dict[str, Any]) -> dict[str, Any]:
    candidate = event.get("candidate") or {}
    review = event.get("result") or {}
    reasons = []
    if candidate.get("scanner_state") != "qualified":
        reasons.append("SCANNER_NOT_EXECUTION_QUALIFIED")
    if candidate.get("tradable") is not True or not candidate.get("t212_ticker"):
        reasons.append("T212_INSTRUMENT_NOT_TRADABLE")
    try:
        spread = float(candidate.get("spread_pct"))
    except (TypeError, ValueError):
        spread = None
    if spread is None:
        reasons.append("SPREAD_UNKNOWN")
    elif spread > 2.5:
        reasons.append("SPREAD_LIMIT")
    if review.get("catalyst_state") not in {"confirmed", "probable"}:
        reasons.append("CATALYST_NOT_VERIFIED")
    if review.get("disposition") != "qualify":
        reasons.append("CATALYST_DISPOSITION_NOT_QUALIFY")
    if not review.get("source"):
        reasons.append("CATALYST_SOURCE_MISSING")
    return {
        "event_id": event.get("id"),
        "symbol": candidate.get("symbol"),
        "t212_ticker": candidate.get("t212_ticker"),
        "candidate": candidate,
        "catalyst_review": review,
        "pre_broker_decision": "PASS" if not reasons else "REJECT",
        "reasons": reasons,
    }


def build_readiness(
    queue: CatalystHandoffQueue,
    broker_fetcher: Callable[[], Any],
    *,
    observed_at: datetime,
    max_reviews: int = MAX_REVIEWS,
) -> dict[str, Any]:
    reviews = queue.completed(min(5, max(1, int(max_reviews))), now=observed_at)
    candidates = [candidate_gate(event) for event in reviews]
    eligible = [item for item in candidates if item["pre_broker_decision"] == "PASS"]
    base = {
        "generated_at": observed_at.astimezone(timezone.utc).isoformat(),
        "environment": "DEMO",
        "live_trading_enabled": False,
        "order_mutation_enabled": False,
        "orders_submitted": 0,
        "reviewed_count": len(candidates),
        "pre_broker_eligible_count": len(eligible),
    }
    if not eligible:
        return {
            **base,
            "state": "NO_CANDIDATE_READY",
            "broker_read_attempted": False,
            "broker_snapshot": None,
            "candidates": candidates,
        }

    try:
        broker = normalize_broker_dashboard(broker_fetcher(), observed_at=observed_at)
    except Exception as exc:
        for item in eligible:
            item["decision"] = "BLOCKED"
            item["reasons"].append("BROKER_READBACK_UNAVAILABLE")
        return {
            **base,
            "state": "BLOCKED",
            "broker_read_attempted": True,
            "broker_error": f"{type(exc).__name__}: {exc}",
            "broker_snapshot": None,
            "candidates": candidates,
        }

    for item in candidates:
        if item["pre_broker_decision"] == "PASS":
            item["decision"] = "READY_FOR_PROPOSAL"
            item["risk_gate_state"] = "PENDING_IMMUTABLE_PROPOSAL"
        else:
            item["decision"] = "REJECT"
    return {
        **base,
        "state": "READY_FOR_PROPOSAL",
        "broker_read_attempted": True,
        "broker_snapshot": broker,
        "candidates": candidates,
    }


def _runtime_fetcher() -> Any:
    from openwebui.tools.trading212_demo_gateway_v03_selfcontained import Tools

    return asyncio.run(Tools().trading_dashboard())


def main() -> int:
    observed = datetime.now(timezone.utc)
    decision = evaluate_session(observed)
    if not decision.allowed:
        payload = {
            "generated_at": observed.isoformat(),
            "environment": "DEMO",
            "state": "SKIPPED",
            "reason": decision.reason,
            "session_gate": decision.to_dict(),
            "live_trading_enabled": False,
            "orders_submitted": 0,
        }
        atomic_json(OUT_PATH, payload)
        print(json.dumps(payload, sort_keys=True))
        return 0

    queue = CatalystHandoffQueue(path=QUEUE_PATH, max_per_day=20)
    payload = build_readiness(queue, _runtime_fetcher, observed_at=observed)
    payload["session_gate"] = decision.to_dict()
    atomic_json(OUT_PATH, payload)
    if payload.get("broker_snapshot"):
        atomic_json(BROKER_PATH, payload["broker_snapshot"])
    print(json.dumps({
        "state": payload["state"],
        "reviewed_count": payload["reviewed_count"],
        "pre_broker_eligible_count": payload["pre_broker_eligible_count"],
        "broker_read_attempted": payload["broker_read_attempted"],
        "orders_submitted": 0,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

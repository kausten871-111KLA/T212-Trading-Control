"""Build a read-only Trading Operations evidence dashboard.

Repository configuration is not runtime proof.  This module therefore keeps
market-data, broker and agent-runtime evidence separate and fails closed when
any supplied artifact contradicts the DEMO-only safety boundary.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping


FAILURE_CODES = {
    "DATA", "MARKET", "STRATEGY", "T212_API", "TOOL", "AUTH",
    "ORCHESTRATION", "EXECUTION", "VERIFICATION", "HUMAN_ACTION",
}


def _time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _assert_demo(artifact: Mapping[str, Any] | None, name: str) -> None:
    if not artifact:
        return
    environment = artifact.get("environment")
    if environment is not None and environment != "DEMO":
        raise ValueError(f"{name} is not DEMO evidence")
    for key in ("live_trading", "live_trading_enabled", "liveTradingEnabled"):
        if artifact.get(key) is True:
            raise ValueError(f"{name} reports LIVE trading enabled")
    if artifact.get("orders_submitted") not in (None, 0):
        raise ValueError(f"{name} reports an order mutation")


def _freshness(
    artifact: Mapping[str, Any] | None,
    *,
    now: datetime,
    maximum_age_seconds: int,
) -> dict[str, Any]:
    if not artifact:
        return {"state": "MISSING", "age_seconds": None, "observed_at": None}
    observed = _time(artifact.get("generated_at") or artifact.get("observed_at"))
    if observed is None:
        return {"state": "UNVERIFIED", "age_seconds": None, "observed_at": None}
    age = max(0.0, (now - observed).total_seconds())
    return {
        "state": "FRESH" if age <= maximum_age_seconds else "STALE",
        "age_seconds": round(age, 3),
        "observed_at": observed.isoformat(),
    }


def _symbols(rows: Iterable[Mapping[str, Any]]) -> set[str]:
    return {
        str(row.get("symbol") or row.get("ticker") or "").upper()
        for row in rows
        if row.get("symbol") or row.get("ticker")
    }


def _failure_code(reason: str) -> str:
    value = reason.upper()
    if "AUTH" in value:
        return "AUTH"
    if "BROKER" in value or "T212" in value:
        return "T212_API"
    if "STALE" in value or "DATA" in value or "TIMESTAMP" in value:
        return "DATA"
    if "MARKET" in value or "SPREAD" in value or "LIQUID" in value:
        return "MARKET"
    if "TOOL" in value or "PROVIDER" in value:
        return "TOOL"
    return "STRATEGY"


def _top_winners(rows: Iterable[Mapping[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    output = []
    for row in rows:
        value = row.get(
            "change_pct",
            row.get("changePercent", row.get("percentChange", row.get("change_percentage"))),
        )
        try:
            change = float(value)
        except (TypeError, ValueError):
            continue
        output.append({
            "symbol": str(row.get("symbol") or "").upper(),
            "change_pct": change,
            "observation_timestamp": row.get("observation_timestamp"),
            "source_truth": "MARKET_DATA",
        })
    return sorted(output, key=lambda item: item["change_pct"], reverse=True)[:limit]


def build_trading_dashboard(
    *,
    market_snapshot: Mapping[str, Any] | None = None,
    scanner: Mapping[str, Any] | None = None,
    readiness: Mapping[str, Any] | None = None,
    new_instruments: Mapping[str, Any] | None = None,
    execution_evidence: Mapping[str, Any] | None = None,
    agent_bindings: Mapping[str, Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Return one deterministic snapshot without calling a provider or broker."""
    now = _time(generated_at) if generated_at else datetime.now(timezone.utc)
    if now is None:
        raise ValueError("generated_at must be timezone-aware")
    artifacts = {
        "market_snapshot": market_snapshot,
        "scanner": scanner,
        "readiness": readiness,
        "new_instruments": new_instruments,
        "execution_evidence": execution_evidence,
    }
    for name, artifact in artifacts.items():
        _assert_demo(artifact, name)

    freshness = {
        "market_snapshot": _freshness(market_snapshot, now=now, maximum_age_seconds=300),
        "scanner": _freshness(scanner, now=now, maximum_age_seconds=300),
        "readiness": _freshness(readiness, now=now, maximum_age_seconds=300),
    }
    broker = (readiness or {}).get("broker_snapshot")
    if broker is not None and not isinstance(broker, Mapping):
        raise ValueError("readiness broker_snapshot must be an object or null")
    _assert_demo(broker, "broker_snapshot")
    freshness["broker"] = _freshness(broker, now=now, maximum_age_seconds=120)

    broker_fresh = freshness["broker"]["state"] == "FRESH"
    portfolio = {
        "state": "BROKER_VERIFIED" if broker_fresh else "UNKNOWN",
        "source_truth": "T212_DEMO" if broker_fresh else None,
        "freshness": freshness["broker"],
        "currency": broker.get("currency") if broker_fresh else None,
        "equity": broker.get("equity") if broker_fresh else None,
        "available_cash": broker.get("available_cash") if broker_fresh else None,
        "open_position_count": broker.get("open_position_count") if broker_fresh else None,
        "pending_order_count": broker.get("pending_order_count") if broker_fresh else None,
        "positions": list(broker.get("positions") or []) if broker_fresh else [],
        "pending_orders": list(broker.get("pending_orders") or []) if broker_fresh else [],
    }

    market_rows = list((market_snapshot or {}).get("rows") or [])
    shortlist = list((scanner or {}).get("shortlist") or [])
    rejected = list((scanner or {}).get("rejected") or [])
    candidates = list((readiness or {}).get("candidates") or [])
    fills = list((execution_evidence or {}).get("broker_verified_fills") or [])
    actual_symbols = _symbols(market_rows)
    surfaced_symbols = _symbols(shortlist)

    reasons: Counter[str] = Counter()
    for row in rejected:
        values = row.get("reasons") or [row.get("reason")]
        for reason in values:
            if reason:
                reasons[str(reason)] += 1
    for row in candidates:
        for reason in row.get("reasons") or []:
            reasons[str(reason)] += 1
    taxonomy: Counter[str] = Counter()
    for reason, count in reasons.items():
        taxonomy[_failure_code(reason)] += count

    roles = []
    for role in (agent_bindings or {}).get("roles", []):
        roles.append({
            "id": role.get("id"),
            "name": role.get("name"),
            "binding_state": role.get("binding_state", "CONFIGURED_ROLE"),
            "runtime_state": role.get("runtime_state", "UNVERIFIED"),
            "persistent_agent": role.get("persistent_agent") is True,
            "broker_write_authority": role.get("broker_write_authority") is True,
        })

    degraded = [name for name, state in freshness.items() if state["state"] != "FRESH"]
    return {
        "generated_at": now.isoformat(),
        "status": "EVIDENCE_COMPLETE" if not degraded else "DEGRADED",
        "degraded_evidence": degraded,
        "safety": {
            "environment": "DEMO",
            "live_trading": False,
            "order_mutation": False,
            "orders_submitted": 0,
        },
        "freshness": freshness,
        "portfolio": portfolio,
        "opportunity": {
            "actual_market_rows": len(market_rows),
            "surfaced": len(shortlist),
            "qualified": int((scanner or {}).get("qualified_count") or 0),
            "top_winners": _top_winners(market_rows),
            "new_on_t212": list((new_instruments or {}).get("instruments") or []),
            "market_data_truth_only": True,
        },
        "decision": {
            "state": (readiness or {}).get("state", "UNKNOWN"),
            "reviewed": int((readiness or {}).get("reviewed_count") or 0),
            "ready_for_proposal": sum(
                1 for row in candidates if row.get("decision") == "READY_FOR_PROPOSAL"
            ),
            "rejected": sum(1 for row in candidates if row.get("decision") == "REJECT"),
            "blocked": sum(1 for row in candidates if row.get("decision") == "BLOCKED"),
            "risk_gate": "PENDING_IMMUTABLE_PROPOSAL",
            "human_approval_required": True,
        },
        "learning": {
            "funnel": {
                "actual": len(actual_symbols),
                "surfaced": len(surfaced_symbols),
                "qualified": int((scanner or {}).get("qualified_count") or 0),
                "ready": sum(1 for row in candidates if row.get("decision") == "READY_FOR_PROPOSAL"),
                "traded": len(fills),
                "missed_actual_not_surfaced": len(actual_symbols - surfaced_symbols),
            },
            "rejection_reasons": dict(sorted(reasons.items())),
            "failure_taxonomy": {
                code: taxonomy.get(code, 0) for code in sorted(FAILURE_CODES)
            },
        },
        "agent_roles": roles,
        "runtime_agents_proven": bool(roles) and all(
            role["runtime_state"] == "VERIFIED" and role["persistent_agent"]
            for role in roles
        ),
    }

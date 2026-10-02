#!/usr/bin/env python3
"""Build an evidence-only PASS/FAIL/MISSING T212 DEMO pre-open gate.

This command never calls a provider, model or broker and never mutates an
order.  Repository files, prompts and historical capability claims cannot
produce GO: every critical dependency requires current runtime or explicit
acceptance evidence.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


def load_object(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _age_seconds(payload: dict[str, Any] | None, now: datetime) -> float | None:
    observed = _time((payload or {}).get("generated_at"))
    return None if observed is None else max(0.0, (now - observed).total_seconds())


def _component(runtime: dict[str, Any] | None, component_id: str) -> dict[str, Any] | None:
    for row in (runtime or {}).get("components", []):
        if isinstance(row, dict) and row.get("id") == component_id:
            return row
    return None


def _acceptance(
    acceptance: dict[str, Any] | None,
    key: str,
    *,
    acceptance_fresh: bool,
) -> tuple[str, str]:
    row = ((acceptance or {}).get("checks") or {}).get(key)
    if not isinstance(row, dict):
        return "MISSING", "No explicit acceptance evidence."
    if not acceptance_fresh:
        return "FAIL", "Acceptance evidence is older than 24 hours or lacks a timestamp."
    if row.get("status") == "PASS" and row.get("evidence"):
        return "PASS", "; ".join(str(item) for item in row["evidence"])
    return "FAIL", str(row.get("blocker") or "Acceptance check did not pass with evidence.")


def build_gate(
    runtime: dict[str, Any] | None,
    dashboard: dict[str, Any] | None,
    acceptance: dict[str, Any] | None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    now = _time(generated_at) if generated_at else datetime.now(timezone.utc)
    if now is None:
        raise ValueError("generated_at must be timezone-aware")

    rows: list[dict[str, Any]] = []

    def add(id_: str, label: str, status: str, evidence: str, next_action: str) -> None:
        rows.append({
            "id": id_, "dependency": label, "critical": True,
            "status": status, "evidence": evidence, "next_action": next_action,
        })

    dashboard_age = _age_seconds(dashboard, now)
    runtime_age = _age_seconds(runtime, now)
    acceptance_age = _age_seconds(acceptance, now)
    dashboard_current = dashboard_age is not None and dashboard_age <= 300
    runtime_current = runtime_age is not None and runtime_age <= 900
    acceptance_fresh = acceptance_age is not None and acceptance_age <= 86400

    safety = (dashboard or {}).get("safety") or {}
    acceptance_unsafe = bool(acceptance) and (
        acceptance.get("environment") != "DEMO"
        or acceptance.get("live_trading_enabled") is not False
    )
    unsafe = acceptance_unsafe or (bool(dashboard) and (
        safety.get("environment") != "DEMO"
        or safety.get("live_trading") is not False
        or safety.get("order_mutation") is not False
        or safety.get("orders_submitted") not in (None, 0)
    ))
    if dashboard is None:
        add("demo_safety", "T212 DEMO only / LIVE disabled", "MISSING", "No dashboard artifact.", "Generate the dashboard from runtime evidence.")
    elif unsafe:
        add("demo_safety", "T212 DEMO only / LIVE disabled", "FAIL", "Dashboard safety invariant is false.", "Stop; restore DEMO-only configuration before any session.")
    else:
        add("demo_safety", "T212 DEMO only / LIVE disabled", "PASS", "DEMO; LIVE=false; order_mutation=false.", "Retain the invariant.")

    portfolio = (dashboard or {}).get("portfolio") or {}
    broker_fresh = ((dashboard or {}).get("freshness") or {}).get("broker", {}).get("state") == "FRESH"
    if dashboard is None or portfolio.get("state") == "UNKNOWN":
        add("broker_account", "Broker/account connection and authoritative state", "MISSING", "No fresh broker-authoritative portfolio evidence.", "Run the read-only T212 DEMO dashboard and rebuild the artifact.")
    elif not dashboard_current or not broker_fresh:
        add("broker_account", "Broker/account connection and authoritative state", "FAIL", "Broker/dashboard evidence is stale.", "Refresh broker evidence immediately before the session.")
    else:
        required = ("equity", "available_cash", "open_position_count", "pending_order_count")
        if any(portfolio.get(field) is None for field in required):
            add("broker_account", "Broker/account connection and authoritative state", "FAIL", "Broker payload is incomplete.", "Restore equity, cash, positions and pending-order readback.")
        else:
            add("broker_account", "Broker/account connection and authoritative state", "PASS", "Fresh T212 DEMO equity/cash/positions/orders are present.", "Retain fresh broker readback.")

    opportunity = (dashboard or {}).get("opportunity") or {}
    market_fresh = ((dashboard or {}).get("freshness") or {}).get("market_snapshot", {}).get("state") == "FRESH"
    if dashboard is None:
        add("broad_discovery", "Broad fresh market discovery", "MISSING", "No dashboard artifact.", "Produce a fresh broad market snapshot.")
    elif not dashboard_current or not market_fresh:
        add("broad_discovery", "Broad fresh market discovery", "FAIL", "Market snapshot is stale or unverified.", "Restore fresh provider data and rerun discovery.")
    elif int(opportunity.get("actual_market_rows") or 0) <= 0:
        add("broad_discovery", "Broad fresh market discovery", "FAIL", "Fresh snapshot contains no market rows.", "Diagnose feed/screener coverage without forcing a trade.")
    else:
        add("broad_discovery", "Broad fresh market discovery", "PASS", f"Fresh rows={opportunity.get('actual_market_rows')}.", "Retain broad discovery evidence.")

    if not opportunity.get("top_winners"):
        add("current_movers", "Current movers / Top Winners", "MISSING", "No timestamped Top Winners rows.", "Populate Top Winners from the current provider snapshot.")
    else:
        add("current_movers", "Current movers / Top Winners", "PASS" if market_fresh else "FAIL", f"Rows={len(opportunity['top_winners'])}; source=MARKET_DATA.", "Refresh with the market snapshot if stale.")

    if dashboard is None:
        add("new_on_t212", "New on T212", "MISSING", "No instrument-diff evidence.", "Run the DEMO instrument cache refresh/diff.")
    elif opportunity.get("new_on_t212_baseline_verified") is not True:
        add("new_on_t212", "New on T212", "MISSING", "No verified prior-cache baseline; an empty list is not proof of no additions.", "Complete a second successful cache refresh against a retained baseline.")
    else:
        add("new_on_t212", "New on T212", "PASS", f"Verified baseline; additions={len(opportunity.get('new_on_t212') or [])}.", "Retain daily diff evidence.")

    cache = ((runtime or {}).get("artifacts") or {}).get("instrument_cache") or {}
    mapping_status, mapping_evidence = _acceptance(acceptance, "instrument_mapping", acceptance_fresh=acceptance_fresh)
    if not runtime_current or cache.get("present") is not True:
        add("instrument_mapping", "T212 instrument mapping/cache", "MISSING" if runtime is None else "FAIL", "Current runtime cache evidence is absent or stale.", "Refresh the shared DEMO cache and rerun mapping acceptance.")
    else:
        add("instrument_mapping", "T212 instrument mapping/cache", mapping_status, mapping_evidence, "Prove exact T212 ticker mapping from the shared cache.")

    for id_, label, key, action in (
        ("relative_volume", "Unusual volume and relative volume", "relative_volume", "Prove relative-volume calculation or its explicit fallback."),
        ("catalyst_news", "Catalyst/news verification", "catalyst_news", "Prove the bounded catalyst consumer and cited source evidence."),
        ("liquidity_spread", "Liquidity/spread gate", "liquidity_spread", "Prove liquidity and spread rejection on current fixtures/runtime evidence."),
        ("cause_effect", "Sector/macro/cause→effect reasoning", "cause_effect", "Prove sourced cause→business impact→price response evidence."),
        ("methodology_risk", "Canonical methodology and risk gates", "methodology_risk", "Prove current knowledge binding and deterministic risk rejection."),
        ("demo_order_cycle", "DEMO order submit and broker verification", "demo_order_cycle", "Run only the separately authorised minimal DEMO acceptance cycle; never LIVE."),
        ("position_lifecycle", "Position monitoring and exits", "position_lifecycle", "Prove monitor→exit→broker-verified closure in DEMO."),
        ("equity_curve", "Dashboard P/L and equity curve", "equity_curve", "Prove broker-backed P/L series and equity-curve persistence."),
        ("automation_owner", "Single session owner, time gate and restart reliability", "automation_owner", "Prove one owner, approved window, deduplication and restart behavior."),
        ("session_authority", "Unattended DEMO session authority and approval gates", "session_authority", "Record exact DEMO-only session authority, immutable-proposal controls and risk-gate behavior; never infer authority from code."),
    ):
        status, evidence = _acceptance(acceptance, key, acceptance_fresh=acceptance_fresh)
        add(id_, label, status, evidence, action)

    audit = ((dashboard or {}).get("learning") or {}).get("missed_green_audit") or {}
    if audit.get("state") == "VERIFIED_ARTIFACT" and audit.get("rows"):
        add("missed_green", "Missed-green analysis and learning", "PASS", f"Audited rows={len(audit['rows'])}; auto-threshold changes=false.", "Retain EOD audit and one evidence-backed improvement.")
    else:
        add("missed_green", "Missed-green analysis and learning", "MISSING", "No populated broker-aware EOD audit artifact.", "Run the read-only EOD missed-green audit after the session.")

    catalyst_component = _component(runtime, "discovery-adapter")
    worker_component = _component(runtime, "discovery-worker")
    if not runtime_current:
        add("runtime_workers", "Runtime worker/timer health", "MISSING", "Runtime evidence is absent or older than 15 minutes.", "Collect fresh systemd/container/runtime evidence.")
    elif not catalyst_component or not worker_component:
        add("runtime_workers", "Runtime worker/timer health", "MISSING", "Required worker components are absent from runtime evidence.", "Collect discovery adapter and worker evidence.")
    elif not (catalyst_component.get("deployed") and worker_component.get("deployed") and worker_component.get("running")):
        add("runtime_workers", "Runtime worker/timer health", "FAIL", "Discovery adapter/worker is not both deployed and running.", "Stop; repair the single approved runtime owner before session start.")
    else:
        add("runtime_workers", "Runtime worker/timer health", "PASS", "Discovery adapter deployed; worker deployed and running.", "Retain fresh health evidence.")

    counts = {status: sum(row["status"] == status for row in rows) for status in ("PASS", "FAIL", "MISSING")}
    go = counts["FAIL"] == 0 and counts["MISSING"] == 0 and len(rows) > 0
    return {
        "generated_at": now.isoformat(),
        "decision": "GO" if go else "NO_GO",
        "scope": "T212_DEMO_PREOPEN_TECHNICAL_READINESS",
        "counts": counts,
        "checks": rows,
        "runtime_evidence_age_seconds": runtime_age,
        "dashboard_age_seconds": dashboard_age,
        "acceptance_evidence_age_seconds": acceptance_age,
        "safety": {
            "environment": "DEMO", "live_trading": False,
            "order_mutation_by_gate": False, "orders_submitted_by_gate": 0,
        },
        "statement": (
            "GO proves only that required evidence passed at generation time; it does not authorize LIVE trading."
            if go else
            "NO_GO: unattended operation must not be represented as ready while any critical dependency is FAIL or MISSING."
        ),
    }


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-evidence", type=Path, required=True)
    parser.add_argument("--dashboard", type=Path, required=True)
    parser.add_argument("--acceptance-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--generated-at")
    args = parser.parse_args()
    payload = build_gate(
        load_object(args.runtime_evidence), load_object(args.dashboard),
        load_object(args.acceptance_evidence), generated_at=args.generated_at,
    )
    atomic_json(args.output, payload)
    print(json.dumps({
        "decision": payload["decision"], "counts": payload["counts"],
        "orders_submitted": 0, "output": str(args.output),
    }, sort_keys=True))
    return 0 if payload["decision"] == "GO" else 2


if __name__ == "__main__":
    raise SystemExit(main())

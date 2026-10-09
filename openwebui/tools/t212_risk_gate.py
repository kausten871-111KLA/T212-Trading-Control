"""Deterministic DEMO risk gate for trade proposals.

No broker calls and no order submission. The gate consumes a proposal plus a
broker-mirrored portfolio snapshot and returns explicit PASS/REJECT evidence.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "webui-control" / "t212-risk-controls.json"


class RiskGateError(ValueError):
    pass


def _num(value: Any, field: str) -> float:
    try:
        number = float(value)
        if isinstance(value, bool) or not math.isfinite(number):
            raise RiskGateError(f"{field} must be finite numeric")
        return number
    except (TypeError, ValueError) as exc:
        raise RiskGateError(f"{field} must be numeric") from exc


def _lower_of(equity: float, spec: Mapping[str, Any], pct_key: str = "equity_pct") -> float:
    pct = _num(spec.get(pct_key), pct_key) / 100.0
    absolute = _num(spec.get("absolute_gbp"), "absolute_gbp")
    return min(equity * pct, absolute)


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise RiskGateError("generated_at must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise RiskGateError("generated_at must include timezone")
    return parsed.astimezone(timezone.utc)


def load_controls(path: str | Path = DEFAULT_CONFIG) -> dict[str, Any]:
    try:
        config = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RiskGateError("risk control config unavailable") from exc
    if config.get("environment") != "DEMO":
        raise RiskGateError("risk controls must remain DEMO")
    return config


def position_count_limit(config: Mapping[str, Any]) -> int | None:
    """Only an explicit, referenced DEMO count-only authorization removes the cap."""
    rules = config.get("controls") or {}
    value = rules.get("max_concurrent_positions", "MISSING")
    policy = config.get("position_count_policy") or {}
    if value is None:
        if (config.get("environment") != "DEMO" or policy.get("mode") != "demo_count_only_relaxation"
                or policy.get("approved") is not True or not policy.get("approval_reference")
                or policy.get("other_risk_limits_unchanged") is not True):
            raise RiskGateError("Count relaxation requires explicit DEMO authorization")
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise RiskGateError("max_concurrent_positions must be a positive integer or authorized null")
    return value


def evaluate(
    proposal: Mapping[str, Any],
    portfolio: Mapping[str, Any],
    *,
    controls: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    config = dict(controls or load_controls())
    rules = config.get("controls") or {}
    authority = config.get("portfolio_authority") or {}

    safety = proposal.get("safety") or {}
    if safety.get("environment") != "DEMO" or safety.get("live_trading") is not False:
        raise RiskGateError("proposal violates DEMO safety")

    if authority.get("broker_truth_authoritative") is not True:
        raise RiskGateError("broker-truth authority must be enabled")
    if portfolio.get("broker_verified") is not True:
        return {
            "decision": "REJECT",
            "reasons": ["BROKER_STATE_UNVERIFIED"],
            "metrics": {},
        }
    if portfolio.get("environment") != "DEMO" or portfolio.get("live_trading_enabled") is not False:
        return {
            "decision": "REJECT",
            "reasons": ["BROKER_ENVIRONMENT_UNSAFE"],
            "metrics": {},
        }
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    try:
        broker_generated = _parse_time(str(portfolio.get("generated_at") or ""))
    except RiskGateError:
        return {
            "decision": "REJECT",
            "reasons": ["BROKER_STATE_UNVERIFIED"],
            "metrics": {},
        }
    broker_age_seconds = max(0.0, (current - broker_generated).total_seconds())
    if broker_age_seconds > _num(
        rules["broker_snapshot_validity_seconds"], "broker snapshot validity"
    ):
        return {
            "decision": "REJECT",
            "reasons": ["BROKER_STATE_STALE"],
            "metrics": {"broker_age_seconds": round(broker_age_seconds, 2)},
        }

    equity = _num(portfolio.get("equity"), "portfolio.equity")
    cash = _num(portfolio.get("available_cash"), "portfolio.available_cash")
    if equity <= 0 or cash < 0:
        raise RiskGateError("portfolio equity/cash invalid")

    entry = proposal.get("entry_range") or {}
    entry_low = _num(entry.get("low"), "entry_range.low")
    entry_high = _num(entry.get("high"), "entry_range.high")
    stop = _num(proposal.get("risk_stop"), "risk_stop")
    quantity = _num(proposal.get("quantity"), "quantity")
    exposure = _num(proposal.get("intended_exposure"), "intended_exposure")
    if min(entry_low, entry_high, stop, quantity, exposure) <= 0 or entry_high < entry_low:
        raise RiskGateError("proposal price/quantity/exposure invalid")

    reference_entry = (entry_low + entry_high) / 2.0
    per_share_risk = max(0.0, reference_entry - stop)
    planned_loss = per_share_risk * quantity

    targets = proposal.get("profit_targets") or []
    first_target = _num(targets[0], "profit_targets[0]") if targets else None
    first_target_reward = max(0.0, first_target - reference_entry) * quantity if first_target is not None else 0.0
    reward_risk = first_target_reward / planned_loss if planned_loss > 0 else 0.0

    max_loss = _lower_of(equity, rules["planned_loss_per_trade"])
    max_position = _lower_of(equity, rules["position_value"])
    max_aggregate = _lower_of(equity, rules["aggregate_open_risk"])

    pending = _num(portfolio.get("pending_commitments", 0), "pending_commitments")
    reserved = _num(portfolio.get("candidate_reservations", 0), "candidate_reservations")
    spendable_cash = max(0.0, cash - pending - reserved)
    open_positions = int(portfolio.get("open_position_count", 0) or 0)
    aggregate_risk = _num(portfolio.get("aggregate_open_risk", 0), "aggregate_open_risk")

    reasons: list[str] = []
    if planned_loss <= 0:
        reasons.append("INVALID_STOP_DISTANCE")
    elif planned_loss > max_loss:
        reasons.append("PLANNED_LOSS_LIMIT")
    if exposure > max_position:
        reasons.append("POSITION_VALUE_LIMIT")
    if exposure > spendable_cash:
        reasons.append("AVAILABLE_CASH_LIMIT")
    count_limit = position_count_limit(config)
    if count_limit is not None and open_positions >= count_limit:
        reasons.append("MAX_CONCURRENT_POSITIONS")
    if aggregate_risk + planned_loss > max_aggregate:
        reasons.append("AGGREGATE_OPEN_RISK_LIMIT")

    spread = proposal.get("spread") or {}
    spread_pct = spread.get("pct_midpoint", spread.get("spread_pct"))
    if spread_pct is None:
        reasons.append("SPREAD_UNKNOWN")
    elif _num(spread_pct, "spread") > _num(rules["normal_session_spread_ceiling_pct_midpoint"], "spread ceiling"):
        reasons.append("SPREAD_LIMIT")

    min_rr = _num(rules["minimum_reward_risk_to_first_target"], "minimum reward risk")
    if reward_risk < min_rr:
        reasons.append("REWARD_RISK_LIMIT")

    friction = proposal.get("expected_friction_pct_planned_risk")
    if friction is not None and _num(friction, "expected friction") > _num(
        rules["max_expected_friction_pct_planned_risk"], "friction limit"
    ):
        reasons.append("FRICTION_LIMIT")

    generated = _parse_time(str(proposal.get("generated_at") or ""))
    age_seconds = max(0.0, (current - generated).total_seconds())
    if age_seconds > _num(rules["proposal_validity_seconds"], "proposal validity"):
        reasons.append("PROPOSAL_STALE")

    current_price = proposal.get("current_reference_price")
    original_price = proposal.get("proposal_reference_price")
    reference_move_pct = None
    if current_price is not None and original_price not in (None, 0):
        original = _num(original_price, "proposal_reference_price")
        current_px = _num(current_price, "current_reference_price")
        reference_move_pct = abs(current_px / original - 1.0) * 100.0
        if reference_move_pct > _num(
            rules["reprice_rescale_if_reference_price_move_pct"],
            "reprice threshold",
        ):
            reasons.append("REPRICE_RESCALE_REQUIRED")

    daily_loss = _num(portfolio.get("daily_loss", 0), "daily_loss")
    daily_start = _num(portfolio.get("starting_daily_equity", equity), "starting_daily_equity")
    daily_limit = min(
        daily_start * _num(rules["daily_loss_stop"]["starting_daily_equity_pct"], "daily loss pct") / 100.0,
        _num(rules["daily_loss_stop"]["absolute_gbp"], "daily loss gbp"),
    )
    if daily_loss >= daily_limit:
        reasons.append("DAILY_LOSS_STOP")

    weekly_loss = _num(portfolio.get("weekly_loss", 0), "weekly_loss")
    weekly_start = _num(portfolio.get("starting_weekly_equity", equity), "starting_weekly_equity")
    weekly_limit = min(
        weekly_start * _num(rules["weekly_loss_stop"]["starting_weekly_equity_pct"], "weekly loss pct") / 100.0,
        _num(rules["weekly_loss_stop"]["absolute_gbp"], "weekly loss gbp"),
    )
    if weekly_loss >= weekly_limit:
        reasons.append("WEEKLY_LOSS_STOP")

    high_water = _num(portfolio.get("high_water_equity", equity), "high_water_equity")
    drawdown = max(0.0, high_water - equity)
    drawdown_limit = min(
        high_water * _num(rules["experiment_drawdown_stop"]["high_water_equity_pct"], "drawdown pct") / 100.0,
        _num(rules["experiment_drawdown_stop"]["absolute_gbp"], "drawdown gbp"),
    )
    if drawdown >= drawdown_limit:
        reasons.append("EXPERIMENT_DRAWDOWN_STOP")

    return {
        "decision": "PASS" if not reasons else "REJECT",
        "reasons": reasons,
        "metrics": {
            "equity": round(equity, 4),
            "spendable_cash": round(spendable_cash, 4),
            "exposure": round(exposure, 4),
            "planned_loss": round(planned_loss, 4),
            "max_planned_loss": round(max_loss, 4),
            "max_position_value": round(max_position, 4),
            "aggregate_open_risk_after": round(aggregate_risk + planned_loss, 4),
            "max_aggregate_open_risk": round(max_aggregate, 4),
            "reward_risk": round(reward_risk, 4),
            "proposal_age_seconds": round(age_seconds, 2),
            "broker_age_seconds": round(broker_age_seconds, 2),
            "reference_move_pct": round(reference_move_pct, 4) if reference_move_pct is not None else None,
        },
        "safety": {
            "environment": "DEMO",
            "live_trading": False,
            "order_mutation": False,
        },
    }

"""Observe-only credit metering, duplicate detection and reconciliation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from openwebui.tools.automation_ledger import validate_run


WORKSPACES = {
    "t212-demo",
    "apps-plugins-bots",
    "you-heal-content",
    "books-publishing",
}
SECRET_MARKERS = ("sk-", "api_key=", "secret=", "password=", "bearer ")


class CreditValidationError(ValueError):
    pass


def _time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise CreditValidationError("timestamp must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise CreditValidationError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def validate_policy(policy: Mapping[str, Any]) -> None:
    if policy.get("mode") != "OBSERVE_AND_REPORT":
        raise CreditValidationError("credit policy must remain observe-and-report")
    if policy.get("currency_spend_authorised") is not False:
        raise CreditValidationError("credit policy cannot authorise spend")
    plan = policy.get("monthly_capacity_plan", {})
    if plan.get("unit") != "CREDITS" or plan.get("enforcement") != "REPORT_ONLY":
        raise CreditValidationError("monthly capacity plan must be report-only credits")
    if plan.get("minimum") != 2_000_000_000 or plan.get("maximum") != 4_000_000_000:
        raise CreditValidationError("monthly capacity plan must preserve the 2-4B range")
    controls = policy.get("controls", {})
    for key in (
        "currency_conversion_enabled",
        "automatic_provider_upgrade",
        "automatic_spend_increase",
    ):
        if controls.get(key) is not False:
            raise CreditValidationError(f"{key} must remain disabled")
    privacy = policy.get("privacy", {})
    for key in ("store_prompt_content", "store_response_content", "store_credentials"):
        if privacy.get(key) is not False:
            raise CreditValidationError(f"{key} must remain disabled")


def validate_event(policy: Mapping[str, Any], event: Mapping[str, Any]) -> None:
    validate_policy(policy)
    missing = set(policy["event_fields"]) - set(event)
    if missing:
        raise CreditValidationError(f"missing event fields: {sorted(missing)}")
    if event["workspace"] not in WORKSPACES:
        raise CreditValidationError("unknown workspace")
    _time(event["timestamp"])
    if not event["event_id"] or not event["run_id"] or not event["provider"]:
        raise CreditValidationError("event, run and provider identifiers are required")
    units = event["units"]
    for key in policy["units"]["required"]:
        if key not in units or not isinstance(units[key], int) or units[key] < 0:
            raise CreditValidationError(f"invalid unit value: {key}")
    if units["total"] != units["input"] + units["output"] + units["cache_read"]:
        raise CreditValidationError("credit total does not match components")
    currency = event["currency_cost"]
    if currency is not None:
        if (
            currency.get("currency") not in {"GBP", "USD"}
            or not isinstance(currency.get("amount"), (int, float))
            or currency["amount"] < 0
        ):
            raise CreditValidationError("invalid currency cost")
    encoded = json.dumps(event, sort_keys=True).lower()
    if any(marker in encoded for marker in SECRET_MARKERS):
        raise CreditValidationError("event appears to contain a secret")
    for forbidden in ("prompt", "response", "credential", "api_key", "secret"):
        if forbidden in event:
            raise CreditValidationError(f"forbidden content field: {forbidden}")


def summarize_usage(
    policy: Mapping[str, Any],
    events: Iterable[Mapping[str, Any]],
    period_start: str,
    period_end: str,
) -> dict[str, Any]:
    validate_policy(policy)
    start, end = _time(period_start), _time(period_end)
    if end < start:
        raise CreditValidationError("period_end cannot precede period_start")

    selected: list[Mapping[str, Any]] = []
    for event in events:
        validate_event(policy, event)
        when = _time(event["timestamp"])
        if start <= when <= end:
            selected.append(event)

    total = sum(event["units"]["total"] for event in selected)
    cache_read = sum(event["units"]["cache_read"] for event in selected)
    by_workspace: dict[str, int] = {}
    by_role: dict[str, int] = {}
    currencies: dict[str, float] = {}
    fingerprints: dict[tuple[str, str, str], list[str]] = {}
    for event in selected:
        by_workspace[event["workspace"]] = (
            by_workspace.get(event["workspace"], 0) + event["units"]["total"]
        )
        role = event["model_role"]
        by_role[role] = by_role.get(role, 0) + event["units"]["total"]
        if event["currency_cost"] is not None:
            code = event["currency_cost"]["currency"]
            currencies[code] = currencies.get(code, 0.0) + float(
                event["currency_cost"]["amount"]
            )
        if event["input_fingerprint"] and not event["cache_hit"]:
            key = (event["workspace"], role, event["input_fingerprint"])
            fingerprints.setdefault(key, []).append(event["event_id"])

    duplicates = [
        {"workspace": key[0], "model_role": key[1], "fingerprint": key[2], "event_ids": ids}
        for key, ids in sorted(fingerprints.items())
        if len(ids) > 1
    ]
    plan = policy["monthly_capacity_plan"]
    if not selected:
        status = "NO_DATA"
    elif total < plan["minimum"]:
        status = "BELOW_PLANNED_RANGE"
    elif total <= plan["maximum"]:
        status = "WITHIN_PLANNED_RANGE"
    else:
        status = "ABOVE_PLANNED_RANGE"

    return {
        "period_start": period_start,
        "period_end": period_end,
        "event_count": len(selected),
        "credits_total": total,
        "credits_cache_read": cache_read,
        "cache_hit_events": sum(bool(event["cache_hit"]) for event in selected),
        "by_workspace": dict(sorted(by_workspace.items())),
        "by_model_role": dict(sorted(by_role.items())),
        "currency_costs": dict(sorted(currencies.items())),
        "uncached_duplicates": duplicates,
        "capacity_status": status,
        "capacity_minimum": plan["minimum"],
        "capacity_maximum": plan["maximum"],
        "spend_authorised": False,
    }


def unmetered_completed_model_runs(
    runs: Iterable[Mapping[str, Any]],
    events: Iterable[Mapping[str, Any]],
) -> list[str]:
    event_run_ids = {event["run_id"] for event in events}
    missing: list[str] = []
    for run in runs:
        validate_run(run)
        if (
            run["status"] == "SUCCEEDED"
            and run.get("model_role")
            and run["run_id"] not in event_run_ids
        ):
            missing.append(run["run_id"])
    return sorted(missing)

"""Deterministic, provider-neutral routing for Open WebUI tasks.

This module selects a logical model role only. Provider credentials and concrete
model IDs remain server-side environment configuration.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence


VISUAL_KINDS = {"image", "screenshot", "scan", "pdf_page_image"}


class RoutingBlocked(RuntimeError):
    """Raised when a required capability has no safely configured model."""


def load_router_config(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    validate_router_config(config)
    return config


def validate_router_config(config: Mapping[str, Any]) -> None:
    roles = config.get("roles")
    if not isinstance(roles, Mapping) or not roles:
        raise ValueError("router config must define roles")
    for role_name, role in roles.items():
        capabilities = role.get("capabilities", [])
        if not isinstance(capabilities, list) or "text" not in capabilities:
            raise ValueError(f"role {role_name!r} must declare text capability")
        if not role.get("model_env"):
            raise ValueError(f"role {role_name!r} must declare model_env")
    vision_roles = [
        name for name, role in roles.items() if "vision" in role.get("capabilities", [])
    ]
    if not vision_roles:
        raise ValueError("at least one genuine vision-capable role is required")
    fallback = config.get("fallback_policy", {})
    if fallback.get("vision_to_text_only") is not False:
        raise ValueError("vision_to_text_only must be false")
    if fallback.get("on_no_eligible_model") != "BLOCK_AND_REPORT":
        raise ValueError("router must block when no eligible model exists")


def _input_kinds(task: Mapping[str, Any]) -> set[str]:
    kinds = set(task.get("input_kinds", []))
    for attachment in task.get("attachments", []):
        if isinstance(attachment, Mapping) and attachment.get("kind"):
            kinds.add(str(attachment["kind"]))
    return kinds


def required_capabilities(task: Mapping[str, Any]) -> set[str]:
    required = {"text"}
    required.update(task.get("required_capabilities", []))
    if task.get("requires_vision") or (_input_kinds(task) & VISUAL_KINDS):
        required.add("vision")
    return required


def _first_role_with_capabilities(
    config: Mapping[str, Any], required: set[str], preferred: str | None = None
) -> str | None:
    roles = config["roles"]
    candidates: Sequence[str] = ([preferred] if preferred else []) + [
        name for name in roles if name != preferred
    ]
    for name in candidates:
        if name is None or name not in roles:
            continue
        if required.issubset(set(roles[name].get("capabilities", []))):
            return name
    return None


def route_task(
    config: Mapping[str, Any],
    task: Mapping[str, Any],
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Return a logged routing decision without invoking any model."""

    validate_router_config(config)
    environment = os.environ if environ is None else environ
    required = required_capabilities(task)
    task_type = str(task.get("task_type", "reasoning"))

    preferred: str | None = None
    human_review = task_type in set(
        config.get("defaults", {}).get("require_human_review_for", [])
    )
    for rule in sorted(config.get("routes", []), key=lambda item: item["priority"], reverse=True):
        when = rule.get("when", {})
        input_match = bool(_input_kinds(task) & set(when.get("any_input_kind", [])))
        capability_match = when.get("requires_capability") in required
        type_match = task_type in set(when.get("task_types", []))
        if input_match or capability_match or type_match:
            preferred = rule["role"]
            human_review = human_review or bool(rule.get("human_review"))
            break

    preferred = preferred or config.get("defaults", {}).get("role")
    selected = _first_role_with_capabilities(config, required, preferred)
    if selected is None:
        raise RoutingBlocked(
            "No configured logical role satisfies: " + ", ".join(sorted(required))
        )

    role = config["roles"][selected]
    env_name = role["model_env"]
    resolved_model = environment.get(env_name)
    if not resolved_model:
        raise RoutingBlocked(
            f"Logical role {selected!r} is eligible but {env_name} is not configured"
        )

    return {
        "workspace": task.get("workspace"),
        "task_type": task_type,
        "required_capabilities": sorted(required),
        "selected_role": selected,
        "resolved_model": resolved_model,
        "fallback_used": selected != preferred,
        "human_review_required": human_review,
        "estimated_cost_tier": role.get("cost_tier"),
        "blocked_reason": None,
    }

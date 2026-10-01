"""Deterministic state and approval gates for Books and You Heal workspaces."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence


class PipelineValidationError(ValueError):
    pass


def validate_pipeline_config(config: Mapping[str, Any]) -> None:
    if config.get("workspace") not in {"books-publishing", "you-heal-content"}:
        raise PipelineValidationError("unsupported workspace")
    states = config.get("states")
    if not isinstance(states, list) or len(states) != len(set(states or [])):
        raise PipelineValidationError("states must be a non-empty unique list")
    policy = config.get("source_policy", {})
    required_policy = {
        "source_files_immutable": True,
        "edits_create_new_version": True,
        "delete_source_allowed": False,
        "overwrite_source_allowed": False,
        "cross_workspace_visibility": False,
        "public_share_allowed": False,
    }
    for key, expected in required_policy.items():
        if policy.get(key) is not expected:
            raise PipelineValidationError(f"unsafe source policy: {key}")
    actions = config.get("actions", {})
    for action in ("publish_enabled", "schedule_enabled", "external_share_enabled"):
        if actions.get(action) is not False:
            raise PipelineValidationError(f"{action} must remain disabled")
    if config["workspace"] == "you-heal-content" and actions.get("spend_enabled") is not False:
        raise PipelineValidationError("You Heal spend must remain disabled")
    transition_policy = config.get("transition_policy", {})
    if transition_policy.get("sequential_only") is not True:
        raise PipelineValidationError("pipeline transitions must be sequential")
    if transition_policy.get("skip_forward_states_allowed") is not False:
        raise PipelineValidationError("forward state skipping must remain disabled")
    if transition_policy.get("published_state_disabled_in_control_plane") is not True:
        raise PipelineValidationError("published state must remain disabled in control plane")


def validate_item(config: Mapping[str, Any], item: Mapping[str, Any]) -> None:
    validate_pipeline_config(config)
    missing = set(config.get("required_state_fields", [])) - set(item)
    if missing:
        raise PipelineValidationError(f"missing item fields: {sorted(missing)}")
    if item["state"] not in config["states"]:
        raise PipelineValidationError("unknown pipeline state")
    if not isinstance(item["version"], int) or item["version"] < 1:
        raise PipelineValidationError("version must be a positive integer")
    if not item["source_refs"]:
        raise PipelineValidationError("at least one source reference is required")
    if item["rights_status"] not in {"UNVERIFIED", "VERIFIED", "RESTRICTED"}:
        raise PipelineValidationError("unknown rights status")
    if item["privacy"] not in {"PRIVATE", "INTERNAL", "PUBLIC_APPROVED"}:
        raise PipelineValidationError("unknown privacy state")
    if not isinstance(item["approvals"], list) or not isinstance(item["checks"], Mapping):
        raise PipelineValidationError("approvals and checks must be structured")


def missing_gates(
    config: Mapping[str, Any],
    item: Mapping[str, Any],
    destination: str,
    approval_actions: Sequence[str] = (),
) -> list[str]:
    validate_item(config, item)
    if destination not in config["states"]:
        raise PipelineValidationError("unknown destination state")

    missing: list[str] = []
    for check in config.get("checks", {}).get(destination, []):
        if item["checks"].get(check) is not True:
            missing.append(f"check:{check}")
    approvals = set(approval_actions)
    approvals.update(
        approval.get("action")
        for approval in item.get("approvals", [])
        if approval.get("state") == "APPROVED"
    )
    for approval in config.get("approvals", {}).get(destination, []):
        if approval not in approvals:
            missing.append(f"approval:{approval}")
    return missing


def transition_item(
    config: Mapping[str, Any],
    item: Mapping[str, Any],
    destination: str,
    new_version: int,
    approval_actions: Sequence[str] = (),
    updated_at: str | None = None,
) -> dict[str, Any]:
    """Return a new versioned state record; never mutates the source item."""

    validate_item(config, item)
    if destination == "PUBLISHED" and config.get("actions", {}).get("publish_enabled") is not True:
        raise PermissionError("publishing is disabled in this control plane")
    if new_version != item["version"] + 1:
        raise PipelineValidationError("each transition must create exactly one new version")

    current_index = config["states"].index(item["state"])
    destination_index = config["states"].index(destination)
    if destination_index < current_index:
        raise PipelineValidationError("backward movement requires an explicit revision workflow")
    if destination_index != current_index + 1:
        raise PipelineValidationError("normal pipeline transitions must advance exactly one state")
    if destination in {"READY_FOR_APPROVAL", "APPROVED", "PUBLISHED"}:
        if item["rights_status"] != "VERIFIED":
            raise PermissionError("transition requires verified rights status")
    gates = missing_gates(config, item, destination, approval_actions)
    if gates:
        raise PermissionError("transition blocked by " + ", ".join(gates))

    updated = deepcopy(dict(item))
    updated["state"] = destination
    updated["version"] = new_version
    updated["updated_at"] = updated_at or datetime.now(timezone.utc).isoformat()
    updated["previous_version_ref"] = f'{item["item_id"]}:v{item["version"]}'
    return updated


def file_visibility_allowed(
    config: Mapping[str, Any],
    item: Mapping[str, Any],
    requesting_workspace: str,
    external: bool = False,
) -> bool:
    validate_item(config, item)
    if requesting_workspace != config["workspace"]:
        return False
    if external:
        return (
            config["source_policy"].get("public_share_allowed") is True
            and item["privacy"] == "PUBLIC_APPROVED"
            and item["rights_status"] == "VERIFIED"
        )
    return True

"""Validation helpers for the least-privilege WebUI connector registry."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


class RegistryValidationError(ValueError):
    pass


def load_registry(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        registry = json.load(handle)
    validate_registry(registry)
    return registry


def _fail(message: str) -> None:
    raise RegistryValidationError(message)


def validate_registry(registry: Mapping[str, Any]) -> None:
    policy = registry.get("default_policy", {})
    if policy.get("fail_closed") is not True:
        _fail("connector registry must fail closed")
    if policy.get("allow_unregistered_connectors") is not False:
        _fail("unregistered connectors must be denied")
    if policy.get("allow_unverified_install") is not False:
        _fail("unverified connector installation must be denied")
    if policy.get("store_secret_values_in_registry") is not False:
        _fail("secret values must never be stored in the registry")

    workspaces = set(registry.get("workspaces", []))
    if not workspaces:
        _fail("at least one workspace is required")

    seen: set[str] = set()
    connectors = registry.get("connectors", [])
    if not isinstance(connectors, list) or not connectors:
        _fail("at least one connector is required")

    for connector in connectors:
        connector_id = connector.get("id")
        if not connector_id or connector_id in seen:
            _fail(f"connector id is missing or duplicated: {connector_id!r}")
        seen.add(connector_id)

        if connector.get("owner_workspace") not in workspaces:
            _fail(f"{connector_id}: unknown owner workspace")
        unknown = set(connector.get("available_to", [])) - workspaces
        if unknown:
            _fail(f"{connector_id}: unknown workspace access {sorted(unknown)}")

        source = connector.get("source", {})
        if source.get("verified") is not True:
            _fail(f"{connector_id}: source must be verified")
        if not connector.get("health_check"):
            _fail(f"{connector_id}: health check is required")
        if not connector.get("approval_level"):
            _fail(f"{connector_id}: approval level is required")
        if not connector.get("fallback"):
            _fail(f"{connector_id}: fallback is required")

        for name in connector.get("secret_env", []):
            if not isinstance(name, str) or not name or "=" in name:
                _fail(f"{connector_id}: secret_env must contain names only")
            if any(marker in name.lower() for marker in ("sk-", "token:", "password:")):
                _fail(f"{connector_id}: apparent secret value in registry")

    trading = next((item for item in connectors if item.get("id") == "t212-demo-readiness"), None)
    if not trading:
        _fail("T212 DEMO readiness connector is required")
    endpoint = trading.get("endpoint_policy", {})
    if endpoint.get("environment") != "DEMO":
        _fail("T212 connector must target DEMO")
    if endpoint.get("live_trading") is not False:
        _fail("T212 LIVE trading must remain disabled")
    if endpoint.get("order_mutation") is not False:
        _fail("overnight connector registry must deny order mutation")
    denied = set(trading.get("denied_operations", []))
    required_denials = {"live_endpoint", "live_credentials", "order_create", "order_modify", "order_cancel"}
    if not required_denials.issubset(denied):
        _fail("T212 connector is missing mandatory denied operations")


def connector_for(
    registry: Mapping[str, Any], connector_id: str, workspace: str
) -> Mapping[str, Any]:
    """Return an eligible connector or fail closed."""

    validate_registry(registry)
    for connector in registry["connectors"]:
        if connector["id"] != connector_id:
            continue
        if workspace not in connector.get("available_to", []):
            raise PermissionError(
                f"connector {connector_id!r} is not available to workspace {workspace!r}"
            )
        if connector.get("state") not in {"connected", "staged"}:
            raise PermissionError(f"connector {connector_id!r} is not usable")
        return connector
    raise PermissionError(f"connector {connector_id!r} is not registered")

"""
Open WebUI <-> ChatGPT MCP Bridge
Read-mostly, local-first bridge for Open WebUI v0.11+.

Security defaults:
- Binds through MCP Streamable HTTP locally.
- Uses the existing Open WebUI API key from OPENWEBUI_API_KEY or OPENWEBUI_ADMIN_API_KEY.
- Broker/trading-capable models are blocked by default.
- Automation/run write actions are blocked unless BRIDGE_ALLOW_WRITES=true.
- Trading-capable model chat is blocked unless BRIDGE_ALLOW_TRADING=true.

This server is intended to run on the same machine as Open WebUI.
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

OWUI_BASE = os.getenv("OPENWEBUI_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
OWUI_KEY = os.getenv("OPENWEBUI_API_KEY") or os.getenv("OPENWEBUI_ADMIN_API_KEY")
ALLOW_WRITES = os.getenv("BRIDGE_ALLOW_WRITES", "false").lower() == "true"
ALLOW_TRADING = os.getenv("BRIDGE_ALLOW_TRADING", "false").lower() == "true"
ALLOWED_MODELS = {
    x.strip()
    for x in os.getenv("BRIDGE_ALLOWED_MODELS", "").split(",")
    if x.strip()
}

TRADING_MARKERS = (
    "trading",
    "t212",
    "trade",
    "broker",
)

mcp = FastMCP(
    "Katie Open WebUI Bridge",
    stateless_http=True,
    json_response=True,
)


def _headers() -> dict[str, str]:
    if not OWUI_KEY:
        raise RuntimeError(
            "Missing Open WebUI API key. Set OPENWEBUI_API_KEY or OPENWEBUI_ADMIN_API_KEY."
        )
    return {
        "Authorization": f"Bearer {OWUI_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _request(method: str, path: str, *, payload: dict[str, Any] | None = None) -> Any:
    url = f"{OWUI_BASE}{path}"
    with httpx.Client(timeout=90.0) as client:
        response = client.request(method, url, headers=_headers(), json=payload)
        response.raise_for_status()
        if not response.content:
            return {"ok": True}
        return response.json()


def _model_is_trading(model_id: str) -> bool:
    lower = model_id.lower()
    return any(marker in lower for marker in TRADING_MARKERS)


def _get_custom_model(model_id: str) -> dict[str, Any] | None:
    try:
        exported = _request("GET", "/api/v1/models/export")
    except Exception:
        return None

    models = exported.get("models", exported) if isinstance(exported, dict) else exported
    if not isinstance(models, list):
        return None

    for model in models:
        if isinstance(model, dict) and model.get("id") == model_id:
            return model
    return None


def _default_context_for_model(model_id: str) -> tuple[list[str], list[str], dict[str, bool]]:
    model = _get_custom_model(model_id) or {}
    meta = model.get("meta") or model.get("info", {}).get("meta") or {}

    tool_ids = list(meta.get("toolIds") or [])
    skill_ids = list(meta.get("skillIds") or [])
    defaults = set(meta.get("defaultFeatureIds") or [])

    features = {
        "web_search": "web_search" in defaults,
        "code_interpreter": "code_interpreter" in defaults,
        "image_generation": "image_generation" in defaults,
        "memory": "memory" in defaults,
    }
    return tool_ids, skill_ids, features


@mcp.tool()
def bridge_health() -> str:
    """Check the local bridge and authenticated Open WebUI API connection."""
    try:
        models = _request("GET", "/api/models")
        count = len(models.get("data", models)) if isinstance(models, dict) else len(models)
        return json.dumps(
            {
                "status": "PASS",
                "openwebui_base": OWUI_BASE,
                "model_count": count,
                "allow_writes": ALLOW_WRITES,
                "allow_trading": ALLOW_TRADING,
            },
            indent=2,
        )
    except Exception as exc:
        return json.dumps({"status": "FAIL", "error": str(exc)}, indent=2)


@mcp.tool()
def list_models() -> str:
    """List models visible to the Open WebUI API key."""
    data = _request("GET", "/api/models")
    return json.dumps(data, indent=2)[:30000]


@mcp.tool()
def list_automations(status: str = "") -> str:
    """List the user's Open WebUI automations and next-run metadata."""
    path = "/api/v1/automations/list"
    if status:
        path += f"?status={status}"
    data = _request("GET", path)
    return json.dumps(data, indent=2)[:30000]


@mcp.tool()
def get_automation_runs(automation_id: str, limit: int = 20) -> str:
    """Read recent run records for one Open WebUI automation."""
    limit = max(1, min(limit, 100))
    data = _request(
        "GET",
        f"/api/v1/automations/{automation_id}/runs?skip=0&limit={limit}",
    )
    return json.dumps(data, indent=2)[:30000]


@mcp.tool()
def send_message(
    model_id: str,
    prompt: str,
    use_model_defaults: bool = True,
) -> str:
    """Send a prompt into a selected Open WebUI model and return its final response.

    Trading/broker-capable model IDs are blocked unless BRIDGE_ALLOW_TRADING=true.
    If BRIDGE_ALLOWED_MODELS is set, the model must also be in that allow-list.
    """
    if ALLOWED_MODELS and model_id not in ALLOWED_MODELS:
        return json.dumps(
            {"status": "BLOCKED", "reason": "model_not_in_bridge_allow_list"}
        )

    if _model_is_trading(model_id) and not ALLOW_TRADING:
        return json.dumps(
            {
                "status": "BLOCKED",
                "reason": "trading_model_blocked_by_default",
                "hint": "Set BRIDGE_ALLOW_TRADING=true only after explicit acceptance testing.",
            }
        )

    payload: dict[str, Any] = {
        "model": model_id,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }

    if use_model_defaults:
        tool_ids, skill_ids, features = _default_context_for_model(model_id)
        if tool_ids:
            payload["tool_ids"] = tool_ids
        if skill_ids:
            payload["skill_ids"] = skill_ids
        payload["features"] = features

    data = _request("POST", "/api/chat/completions", payload=payload)
    return json.dumps(data, indent=2)[:50000]


@mcp.tool()
def run_automation(automation_id: str) -> str:
    """Run an existing Open WebUI automation now.

    Disabled by default. Requires BRIDGE_ALLOW_WRITES=true.
    """
    if not ALLOW_WRITES:
        return json.dumps(
            {
                "status": "BLOCKED",
                "reason": "bridge_writes_disabled",
                "hint": "Set BRIDGE_ALLOW_WRITES=true only after explicit acceptance testing.",
            }
        )

    data = _request("POST", f"/api/v1/automations/{automation_id}/run")
    return json.dumps(data, indent=2)[:30000]


if __name__ == "__main__":
    mcp.run(transport="streamable-http")

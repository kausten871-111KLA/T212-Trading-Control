"""
title: Contabo Operations Bridge
author: OpenAI Engineering
description: Authenticated named operations on the user's Contabo host. No shell or arbitrary command execution and no broker orders.
version: 0.1.0
"""
import json
from pathlib import Path
from typing import Literal
import httpx
from pydantic import BaseModel, Field


class Tools:
    class Valves(BaseModel):
        endpoint: str = Field(
            default="/run/contabo-bridge/command.sock",
            description="Private Docker-bridge endpoint, never public internet.",
        )
        bridge_token: str = Field(
            default="",
            description="Dedicated host command-bridge token. Store in encrypted tool valves.",
            json_schema_extra={"input": {"type": "password"}},
        )

    def __init__(self):
        self.valves = self.Valves()

    async def contabo_command(
        self,
        command: Literal[
            "runtime_status", "webui_health", "open_acceptance",
            "repo_revision", "data_key_status", "alpha_vantage_daily"
        ] = "runtime_status",
        symbol: str = "IBM",
    ) -> str:
        """Invoke one predefined Contabo operation and return verified host output.

        :param command: Select runtime_status, webui_health, open_acceptance, repo_revision,
        data_key_status or alpha_vantage_daily. No free-form shell or orders.
        :param symbol: Market symbol, e.g. IBM or TSCO.LON, for alpha_vantage_daily only.
        """
        permitted = {
            "runtime_status", "webui_health", "open_acceptance",
            "repo_revision", "data_key_status", "alpha_vantage_daily"
        }
        if command not in permitted:
            return json.dumps({"ok": False, "error": "command_not_allowed"})
        url = self.valves.endpoint.strip()
        token = Path("/run/contabo-bridge/bridge.token").read_text().strip()
        if not token:
            return json.dumps({"ok": False, "error": "bridge_token_not_configured"})
        if url != "/run/contabo-bridge/command.sock":
            return json.dumps({"ok": False, "error": "unexpected_endpoint"})
        try:
            async with httpx.AsyncClient(timeout=45, trust_env=False, transport=httpx.AsyncHTTPTransport(uds=url)) as client:
                response = await client.post(
                    "http://localhost/command",
                    json={"command": command, "symbol": symbol},
                    headers={"X-Bridge-Token": token, "Accept": "application/json"},
                )
                return response.text[:15000] if response.status_code == 200 else json.dumps(
                    {"ok": False, "http_status": response.status_code,
                     "error": "bridge_request_failed"})
        except Exception as exc:
            return json.dumps({"ok": False, "error_type": type(exc).__name__})

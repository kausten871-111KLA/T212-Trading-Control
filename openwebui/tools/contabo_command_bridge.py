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


    async def model_task(
        self,
        action: Literal["create", "status", "cancel"],
        task_id: str = "",
        job_kind: Literal["research", "analysis", "engineering", "review"] = "research",
        instruction: str = "",
        scheduled_at_utc: str = "",
        dedupe_key: str = "",
        cost_tier: Literal["light", "pro"] = "light",
        max_attempts: int = 3,
    ) -> str:
        """Create, inspect or cancel a persistent DeepSeek research task.

        Uses the existing private Contabo bridge with a SEPARATE dedicated
        model-task token. It does not execute inference, place broker orders,
        create another scheduler or select a different owner model. It remains
        unavailable until the host operator provisions the dedicated secret
        and installs the matching audited host endpoint.

        :param action: create, status or cancel a background research task.
        :param task_id: Existing task ID; required for status/cancel.
        :param job_kind: research, analysis, engineering or review.
        :param instruction: Specific background task instruction (create only).
        :param scheduled_at_utc: Timezone-aware ISO-8601 UTC execution time.
        :param dedupe_key: Stable unique task key to prevent duplicate work.
        :param cost_tier: light by default; pro requires separate host approval.
        :param max_attempts: Number of retry attempts, 1 through 10.
        """
        if action not in {"create", "status", "cancel"}:
            return json.dumps({"ok": False, "error": "invalid_action"})
        if self.valves.endpoint.strip() != "/run/contabo-bridge/command.sock":
            return json.dumps({"ok": False, "error": "unexpected_endpoint"})
        if action == "create":
            if (not isinstance(instruction, str) or not 1 <= len(instruction.strip()) <= 12000
                    or not isinstance(dedupe_key, str) or not 1 <= len(dedupe_key) <= 180
                    or not isinstance(scheduled_at_utc, str) or not scheduled_at_utc.strip()
                    or type(max_attempts) is not int or not 1 <= max_attempts <= 10):
                return json.dumps({"ok": False, "error": "invalid_create_fields"})
            payload = {
                "job_kind": job_kind, "instruction": instruction.strip(),
                "scheduled_at_utc": scheduled_at_utc, "dedupe_key": dedupe_key,
                "cost_tier": cost_tier, "max_attempts": max_attempts,
            }
        else:
            if not isinstance(task_id, str) or not task_id.strip():
                return json.dumps({"ok": False, "error": "task_id_required"})
            payload = {"task_id": task_id}
        # NEVER reuse the general command bridge token: the model-task
        # endpoint has a separate credential and is disabled by default.
        secret_file = Path("/run/contabo-bridge/model-task.token")
        try:
            secret = secret_file.read_text().strip()
        except (OSError, UnicodeError):
            return json.dumps({"ok": False, "error": "model_task_not_configured"})
        if len(secret) < 48 or not secret.isascii():
            return json.dumps({"ok": False, "error": "model_task_not_configured"})
        try:
            async with httpx.AsyncClient(
                timeout=20, trust_env=False,
                transport=httpx.AsyncHTTPTransport(uds=self.valves.endpoint.strip()),
            ) as client:
                response = await client.post(
                    "http://localhost/model-task",
                    json={"action": action, "payload": payload},
                    headers={"X-Model-Task-Token": secret, "Accept": "application/json"},
                )
                if response.status_code == 200:
                    return response.text[:15000]
                return json.dumps({"ok": False, "http_status": response.status_code,
                                   "error": "model_task_request_failed"})
        except Exception as exc:
            return json.dumps({"ok": False, "error_type": type(exc).__name__})

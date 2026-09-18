"""
title: Open WebUI Site Configurator
author: Katie / OpenAI
description: Local Open WebUI workspace audit and additive configuration tool. Uses a server-side Open WebUI API key.
version: 0.1.0
"""

import os
import json
import httpx


class Tools:
    def __init__(self):
        self.base_url = os.getenv("OPENWEBUI_BASE_URL", "http://localhost:8080").rstrip("/")

    def _key(self):
        return os.getenv("OPENWEBUI_ADMIN_API_KEY", "").strip()

    def _show(self, value):
        if isinstance(value, str):
            return value
        return json.dumps(value, indent=2, default=str)

    async def _request(self, method, path, json_body=None):
        key = self._key()
        if not key:
            return None, (
                "OPENWEBUI_ADMIN_API_KEY is not available to the Open WebUI server. "
                "Load a temporary local API key into the server environment first."
            )

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.request(
                    method,
                    f"{self.base_url}{path}",
                    json=json_body,
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                )
                try:
                    data = response.json()
                except Exception:
                    data = response.text
                if response.is_error:
                    return None, f"Open WebUI API error {response.status_code}: {data}"
                return data, None
        except Exception as exc:
            return None, f"Open WebUI API connection error: {type(exc).__name__}: {exc}"

    async def audit_workspace(self) -> str:
        """
        Audit the local Open WebUI workspace without changing anything.
        Returns custom models, tools, skills and knowledge collections visible to the API-key owner.
        """
        endpoints = {
            "models": "/api/v1/models/export",
            "tools": "/api/v1/tools/export",
            "skills": "/api/v1/skills/export",
            "knowledge": "/api/v1/knowledge/",
        }
        result = {}
        for label, path in endpoints.items():
            data, error = await self._request("GET", path)
            result[label] = {"error": error} if error else data
        return self._show(result)

    async def export_models(self) -> str:
        """
        Export current custom Workspace Models. Use before changing a model so the exact live JSON
        can be inspected and preserved.
        """
        data, error = await self._request("GET", "/api/v1/models/export")
        return error or self._show(data)

    async def import_models_additive(self, models_json: str) -> str:
        """
        Add or update custom Workspace Models using Open WebUI's additive import endpoint.
        This never intentionally deletes models. First export current models and modify only the target model.
        :param models_json: JSON array containing complete Open WebUI model objects/forms to import.
        """
        try:
            models = json.loads(models_json)
        except Exception as exc:
            return f"Invalid models JSON: {exc}"
        if not isinstance(models, list):
            return "models_json must decode to a JSON array."
        data, error = await self._request(
            "POST",
            "/api/v1/models/import",
            json_body={"models": models},
        )
        return error or self._show({"ok": True, "result": data})

    async def create_skill(
        self,
        skill_id: str,
        name: str,
        description: str,
        content: str,
    ) -> str:
        """
        Create one reusable Open WebUI Skill. Additive only; it will not overwrite an existing skill ID.
        """
        payload = {
            "id": skill_id,
            "name": name,
            "description": description,
            "content": content,
            "meta": {"tags": []},
            "is_active": True,
            "access_grants": [],
        }
        data, error = await self._request(
            "POST",
            "/api/v1/skills/create",
            json_body=payload,
        )
        return error or self._show(data)

    async def update_skill(
        self,
        skill_id: str,
        name: str,
        description: str,
        content: str,
    ) -> str:
        """
        Update one existing Open WebUI Skill by exact ID. Use only after audit_workspace confirms the target.
        """
        payload = {
            "id": skill_id,
            "name": name,
            "description": description,
            "content": content,
            "meta": {"tags": []},
            "is_active": True,
            "access_grants": [],
        }
        data, error = await self._request(
            "POST",
            f"/api/v1/skills/id/{skill_id}/update",
            json_body=payload,
        )
        return error or self._show(data)

    async def list_tools(self) -> str:
        """List current local/OpenAPI/MCP tools without changing them."""
        data, error = await self._request("GET", "/api/v1/tools/")
        return error or self._show(data)

    async def list_knowledge(self) -> str:
        """List current Knowledge collections without changing them."""
        data, error = await self._request("GET", "/api/v1/knowledge/")
        return error or self._show(data)

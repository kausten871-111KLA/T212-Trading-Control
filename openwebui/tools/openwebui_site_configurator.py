"""
title: Open WebUI Site Configurator
author: Katie / OpenAI
description: Local Open WebUI workspace audit and additive configuration tool. Uses a server-side Open WebUI API key.
version: 0.3.0
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


    async def install_or_update_skill_from_github(
        self,
        skill_id: str,
        name: str,
        description: str,
        raw_url: str,
    ) -> str:
        """
        Install or update one Open WebUI Skill directly from the project's public GitHub raw URL.
        Only the kausten871-111KLA/T212-Trading-Control repository is allowed.
        Audit-first behavior: checks whether the skill already exists, then creates or updates it.
        """
        allowed_prefix = (
            "https://raw.githubusercontent.com/"
            "kausten871-111KLA/T212-Trading-Control/"
        )
        if not raw_url.startswith(allowed_prefix):
            return "Blocked: raw_url is outside the approved T212-Trading-Control GitHub repository."

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                source = await client.get(raw_url)
                source.raise_for_status()
                content = source.text
        except Exception as exc:
            return f"Failed to fetch GitHub skill source: {type(exc).__name__}: {exc}"

        payload = {
            "id": skill_id,
            "name": name,
            "description": description,
            "content": content,
            "meta": {"tags": ["managed-by-configurator"]},
            "is_active": True,
            "access_grants": [],
        }

        existing, error = await self._request(
            "GET",
            f"/api/v1/skills/id/{skill_id}",
        )

        if error and "404" not in error:
            return error

        if existing:
            data, error = await self._request(
                "POST",
                f"/api/v1/skills/id/{skill_id}/update",
                json_body=payload,
            )
            action = "updated"
        else:
            data, error = await self._request(
                "POST",
                "/api/v1/skills/create",
                json_body=payload,
            )
            action = "created"

        if error:
            return error

        return self._show({
            "ok": True,
            "action": action,
            "skill_id": skill_id,
            "name": name,
        })

    async def install_or_update_tool_from_github(
        self,
        tool_id: str,
        name: str,
        description: str,
        raw_url: str,
    ) -> str:
        """
        Install or update one local Open WebUI Python Tool from the project's public GitHub raw URL.
        Only the kausten871-111KLA/T212-Trading-Control repository is allowed.
        Use only for reviewed project tools. This executes Python inside Open WebUI when installed.
        """
        allowed_prefix = (
            "https://raw.githubusercontent.com/"
            "kausten871-111KLA/T212-Trading-Control/"
        )
        if not raw_url.startswith(allowed_prefix):
            return "Blocked: raw_url is outside the approved T212-Trading-Control GitHub repository."

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                source = await client.get(raw_url)
                source.raise_for_status()
                content = source.text
        except Exception as exc:
            return f"Failed to fetch GitHub tool source: {type(exc).__name__}: {exc}"

        payload = {
            "id": tool_id,
            "name": name,
            "content": content,
            "meta": {
                "description": description,
                "manifest": {},
                "has_user_valves": False,
            },
            "access_grants": [],
        }

        existing, error = await self._request(
            "GET",
            f"/api/v1/tools/id/{tool_id}",
        )

        if error and "404" not in error and "401" not in error:
            return error

        if existing:
            data, error = await self._request(
                "POST",
                f"/api/v1/tools/id/{tool_id}/update",
                json_body=payload,
            )
            action = "updated"
        else:
            data, error = await self._request(
                "POST",
                "/api/v1/tools/create",
                json_body=payload,
            )
            action = "created"

        if error:
            return error

        return self._show({
            "ok": True,
            "action": action,
            "tool_id": tool_id,
            "name": name,
        })


    async def create_knowledge_from_github(
        self,
        knowledge_name: str,
        description: str,
        raw_url: str,
        filename: str = "knowledge.md",
    ) -> str:
        """
        Create or reuse one local Open WebUI Knowledge collection, upload a reviewed Markdown file
        from the approved GitHub repository, and attach it to that collection.
        Additive only: this does not delete existing knowledge or files.
        """
        allowed_prefix = (
            "https://raw.githubusercontent.com/"
            "kausten871-111KLA/T212-Trading-Control/"
        )
        if not raw_url.startswith(allowed_prefix):
            return "Blocked: raw_url is outside the approved T212-Trading-Control GitHub repository."

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                source = await client.get(raw_url)
                source.raise_for_status()
                content = source.text
        except Exception as exc:
            return f"Failed to fetch GitHub knowledge source: {type(exc).__name__}: {exc}"

        knowledge_data, error = await self._request("GET", "/api/v1/knowledge/")
        if error:
            return error

        items = []
        if isinstance(knowledge_data, dict):
            items = knowledge_data.get("items") or []
        elif isinstance(knowledge_data, list):
            items = knowledge_data

        knowledge = next(
            (item for item in items if item.get("name") == knowledge_name),
            None,
        )

        if not knowledge:
            knowledge, error = await self._request(
                "POST",
                "/api/v1/knowledge/create",
                json_body={
                    "name": knowledge_name,
                    "description": description,
                    "access_grants": [],
                },
            )
            if error:
                return error

        knowledge_id = knowledge.get("id")
        if not knowledge_id:
            return f"Knowledge creation/list response did not contain an id: {knowledge}"

        existing_files, error = await self._request(
            "GET",
            f"/api/v1/knowledge/{knowledge_id}/files?query={filename}",
        )
        if error:
            return error

        existing_items = []
        if isinstance(existing_files, dict):
            existing_items = existing_files.get("items") or []

        for item in existing_items:
            visible_name = (
                item.get("filename")
                or (item.get("meta") or {}).get("name")
                or ""
            )
            if visible_name.endswith(filename):
                return self._show({
                    "ok": True,
                    "action": "already-present",
                    "knowledge_id": knowledge_id,
                    "knowledge_name": knowledge_name,
                    "filename": filename,
                    "file_id": item.get("id"),
                })

        key = self._key()
        if not key:
            return "OPENWEBUI_ADMIN_API_KEY is not available to Open WebUI."

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                upload = await client.post(
                    f"{self.base_url}/api/v1/files/?process=true&process_in_background=false",
                    headers={"Authorization": f"Bearer {key}"},
                    files={
                        "file": (
                            filename,
                            content.encode("utf-8"),
                            "text/markdown",
                        )
                    },
                )
                try:
                    upload_data = upload.json()
                except Exception:
                    upload_data = upload.text

                if upload.is_error:
                    return f"Open WebUI file upload error {upload.status_code}: {upload_data}"

        except Exception as exc:
            return f"Open WebUI file upload connection error: {type(exc).__name__}: {exc}"

        file_id = upload_data.get("id") if isinstance(upload_data, dict) else None
        if not file_id:
            return f"File upload did not return an id: {upload_data}"

        attached, error = await self._request(
            "POST",
            f"/api/v1/knowledge/{knowledge_id}/file/add",
            json_body={"file_id": file_id},
        )
        if error:
            return error

        return self._show({
            "ok": True,
            "action": "created-and-attached",
            "knowledge_id": knowledge_id,
            "knowledge_name": knowledge_name,
            "filename": filename,
            "file_id": file_id,
        })

    async def list_tools(self) -> str:
        """List current local/OpenAPI/MCP tools without changing them."""
        data, error = await self._request("GET", "/api/v1/tools/")
        return error or self._show(data)

    async def list_knowledge(self) -> str:
        """List current Knowledge collections without changing them."""
        data, error = await self._request("GET", "/api/v1/knowledge/")
        return error or self._show(data)

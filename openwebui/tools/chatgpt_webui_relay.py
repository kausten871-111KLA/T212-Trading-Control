"""
title: ChatGPT WebUI Relay
author: Katie / OpenAI
description: Bounded GitHub Issue relay between ChatGPT and this local Open WebUI instance. Coordination only; never broker evidence and never executes trades.
version: 0.1.0
"""

import os
import json
from typing import Optional
import httpx


class Tools:
    def __init__(self):
        self.owner = "kausten871-111KLA"
        self.repo = "T212-Trading-Control"
        self.issue_number = 5
        self.api_base = "https://api.github.com"

    def _token(self):
        return os.getenv("GITHUB_RELAY_TOKEN", "").strip()

    def _headers(self, write: bool = False):
        token = self._token()
        if write and not token:
            return None
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "OpenWebUI-ChatGPT-Relay",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _show(self, value):
        if isinstance(value, str):
            return value
        return json.dumps(value, indent=2, default=str)

    async def _request(self, method: str, path: str, json_body=None, write: bool = False):
        headers = self._headers(write=write)
        if headers is None:
            return None, (
                "GITHUB_RELAY_TOKEN is not loaded in the Open WebUI server process. "
                "Create a fine-grained GitHub token limited to this repository with Issues read/write, "
                "load it server-side, and never paste it into chat."
            )
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.request(
                    method,
                    f"{self.api_base}{path}",
                    headers=headers,
                    json=json_body,
                )
                try:
                    data = response.json()
                except Exception:
                    data = response.text
                if response.is_error:
                    return None, f"GitHub relay error {response.status_code}: {data}"
                return data, None
        except Exception as exc:
            return None, f"GitHub relay connection error: {type(exc).__name__}: {exc}"

    async def relay_status(self) -> str:
        """
        Read the dedicated relay issue metadata.
        Coordination only; never touches Trading 212.
        """
        data, error = await self._request(
            "GET",
            f"/repos/{self.owner}/{self.repo}/issues/{self.issue_number}",
        )
        if error:
            return error
        return self._show(
            {
                "relay": "ChatGPT <-> Open WebUI",
                "repository": f"{self.owner}/{self.repo}",
                "issueNumber": self.issue_number,
                "issueState": data.get("state"),
                "commentCount": data.get("comments"),
                "tokenLoaded": bool(self._token()),
                "readOnlyWithoutToken": True,
                "writesRequireToken": True,
                "note": "Relay messages are coordination evidence only, never broker evidence.",
            }
        )

    async def relay_read(self, limit: int = 20) -> str:
        """
        Read recent relay comments.
        Public repository reads can work without a token.
        :param limit: Number of recent comments to return, 1-50.
        """
        limit = max(1, min(int(limit), 50))
        data, error = await self._request(
            "GET",
            f"/repos/{self.owner}/{self.repo}/issues/{self.issue_number}/comments?per_page=100",
        )
        if error:
            return error
        rows = []
        for item in (data or [])[-limit:]:
            rows.append(
                {
                    "id": item.get("id"),
                    "createdAt": item.get("created_at"),
                    "updatedAt": item.get("updated_at"),
                    "author": (item.get("user") or {}).get("login"),
                    "body": item.get("body"),
                    "url": item.get("html_url"),
                }
            )
        return self._show(
            {
                "relayIssue": self.issue_number,
                "count": len(rows),
                "comments": rows,
            }
        )

    async def relay_post(
        self,
        message: str,
        category: str = "STATUS",
    ) -> str:
        """
        Post a bounded status/result message from Open WebUI to ChatGPT through the dedicated relay issue.
        Requires GITHUB_RELAY_TOKEN loaded server-side.
        Never include credentials, secrets, protected IP, or raw personal data.
        :param message: Concise coordination/status message.
        :param category: STATUS, BLOCKER, ACK, RESULT, or WEBUI->CHATGPT.
        """
        message = (message or "").strip()
        if not message:
            return "Relay message is empty."
        if len(message) > 8000:
            return "Relay message too long; keep it under 8000 characters."

        category = (category or "STATUS").strip().upper()
        allowed = {"STATUS", "BLOCKER", "ACK", "RESULT", "WEBUI->CHATGPT"}
        if category not in allowed:
            category = "STATUS"

        prefix = "[WEBUI→CHATGPT]" if category == "WEBUI->CHATGPT" else f"[{category}]"
        body = f"{prefix}\n\n{message}"

        data, error = await self._request(
            "POST",
            f"/repos/{self.owner}/{self.repo}/issues/{self.issue_number}/comments",
            json_body={"body": body},
            write=True,
        )
        if error:
            return error

        return self._show(
            {
                "status": "POSTED",
                "issueNumber": self.issue_number,
                "commentId": data.get("id"),
                "url": data.get("html_url"),
            }
        )

"""
title: Trading 212 DEMO Execution
author: Katie / OpenAI
description: Trading 212 paper-trading execution bridge for Open WebUI.
version: 0.2.0
"""

import os
import re
import time
import httpx


class Pipe:
    def __init__(self):
        self.base_url = "https://demo.trading212.com/api/v0"
        self.last_submission = None
        self.last_submission_time = 0.0

    def _credentials(self):
        return (
            os.getenv("T212_DEMO_API_KEY", "").strip(),
            os.getenv("T212_DEMO_API_SECRET", "").strip(),
        )

    async def _request(self, method, path, json=None, params=None):
        key, secret = self._credentials()
        if not key or not secret:
            return None, "T212 DEMO credentials are not available to Open WebUI."

        try:
            async with httpx.AsyncClient(
                timeout=30.0,
                auth=httpx.BasicAuth(key, secret),
            ) as client:
                response = await client.request(
                    method,
                    f"{self.base_url}{path}",
                    json=json,
                    params=params,
                    headers={"Accept": "application/json", "Content-Type": "application/json"},
                )
                try:
                    data = response.json()
                except Exception:
                    data = response.text

                if response.is_error:
                    return None, f"T212 DEMO API error {response.status_code}: {data}"
                return data, None
        except Exception as exc:
            return None, f"T212 DEMO connection error: {type(exc).__name__}: {exc}"

    async def _submit_market(self, side, ticker, quantity, extended_hours=False, __event_emitter__=None):
        quantity = float(quantity)
        if quantity <= 0:
            return "Quantity must be greater than zero."

        fingerprint = (side, ticker, round(quantity, 8), bool(extended_hours))
        now = time.monotonic()
        if fingerprint == self.last_submission and now - self.last_submission_time < 30:
            return "DUPLICATE BLOCKED: identical DEMO order submitted less than 30 seconds ago."

        signed_quantity = quantity if side == "BUY" else -quantity
        payload = {
            "ticker": ticker,
            "quantity": signed_quantity,
            "extendedHours": bool(extended_hours),
        }

        if __event_emitter__:
            await __event_emitter__({
                "type": "status",
                "data": {
                    "description": f"Submitting T212 DEMO {side}: {ticker} x {quantity}",
                    "done": False,
                },
            })

        self.last_submission = fingerprint
        self.last_submission_time = now
        data, error = await self._request("POST", "/equity/orders/market", json=payload)
        if error:
            return error

        if __event_emitter__:
            await __event_emitter__({
                "type": "status",
                "data": {
                    "description": "T212 DEMO accepted the order request.",
                    "done": True,
                },
            })

        return {
            "environment": "DEMO",
            "action": side,
            "ticker": ticker,
            "quantity": quantity,
            "extendedHours": bool(extended_hours),
            "broker_response": data,
        }

    async def pipe(self, body: dict, __event_emitter__=None):
        messages = body.get("messages", [])
        if not messages:
            return "No command supplied."

        command = str(messages[-1].get("content", "")).strip()

        if command.upper() == "HELP":
            return (
                "T212 DEMO Execution Bridge v0.2\n\n"
                "FIND <name|symbol>\n"
                "POSITIONS\n"
                "POSITION <T212_TICKER>\n"
                "ORDERS\n"
                "ORDER <id>\n"
                "BUY <T212_TICKER> <QUANTITY>\n"
                "BUY EXT <T212_TICKER> <QUANTITY>\n"
                "SELL <T212_TICKER> <QUANTITY>\n"
                "SELL EXT <T212_TICKER> <QUANTITY>\n"
                "CLOSE <T212_TICKER>\n\n"
                "DEMO environment only."
            )

        match = re.fullmatch(r"FIND\s+(.+)", command, flags=re.IGNORECASE)
        if match:
            query = match.group(1).strip().lower()
            data, error = await self._request("GET", "/equity/metadata/instruments")
            if error:
                return error
            matches = []
            for inst in data if isinstance(data, list) else []:
                haystack = " ".join(str(inst.get(k, "")) for k in ("ticker", "name", "shortName", "isin")).lower()
                if query in haystack:
                    matches.append({
                        "name": inst.get("name"),
                        "shortName": inst.get("shortName"),
                        "ticker": inst.get("ticker"),
                        "currencyCode": inst.get("currencyCode"),
                        "type": inst.get("type"),
                        "extendedHours": inst.get("extendedHours"),
                        "maxOpenQuantity": inst.get("maxOpenQuantity"),
                    })
            return matches[:10] if matches else f"No T212 DEMO instrument matched '{match.group(1).strip()}'."

        if command.upper() == "POSITIONS":
            data, error = await self._request("GET", "/equity/positions")
            return error or data

        match = re.fullmatch(r"POSITION\s+([A-Za-z0-9._-]+)", command, flags=re.IGNORECASE)
        if match:
            ticker = match.group(1).upper()
            data, error = await self._request("GET", "/equity/positions", params={"ticker": ticker})
            return error or data

        if command.upper() == "ORDERS":
            data, error = await self._request("GET", "/equity/orders")
            return error or data

        match = re.fullmatch(r"ORDER\s+(\d+)", command, flags=re.IGNORECASE)
        if match:
            data, error = await self._request("GET", f"/equity/orders/{match.group(1)}")
            return error or data

        match = re.fullmatch(
            r"(BUY|SELL)(?:\s+(EXT))?\s+([A-Za-z0-9._-]+)\s+([0-9]+(?:\.[0-9]+)?)",
            command,
            flags=re.IGNORECASE,
        )
        if match:
            side = match.group(1).upper()
            extended = bool(match.group(2))
            ticker = match.group(3).upper()
            quantity = float(match.group(4))
            return await self._submit_market(side, ticker, quantity, extended, __event_emitter__)

        match = re.fullmatch(r"CLOSE\s+([A-Za-z0-9._-]+)", command, flags=re.IGNORECASE)
        if match:
            ticker = match.group(1).upper()
            positions, error = await self._request("GET", "/equity/positions", params={"ticker": ticker})
            if error:
                return error
            if not isinstance(positions, list) or not positions:
                return f"No open DEMO position found for {ticker}."
            available = sum(float(p.get("quantityAvailableForTrading") or 0) for p in positions)
            if available <= 0:
                return f"No quantity available to close for {ticker}."
            return await self._submit_market("SELL", ticker, available, False, __event_emitter__)

        return "Command not recognised. Use HELP."

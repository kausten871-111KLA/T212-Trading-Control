"""
title: Trading 212 DEMO Execution
author: Katie / OpenAI
description: Single Trading 212 paper-trading gateway for Open WebUI.
version: 0.3.1
"""

import os
import re
import time
import json
import httpx


class Pipe:
    def __init__(self):
        self.base_url = "https://demo.trading212.com/api/v0"
        self.last_submission = None
        self.last_submission_time = 0.0

    def _show(self, value):
        if isinstance(value, str):
            return value
        return json.dumps(value, indent=2, default=str)

    def _credentials(self):
        return (
            os.getenv("T212_DEMO_API_KEY", "").strip(),
            os.getenv("T212_DEMO_API_SECRET", "").strip(),
        )

    async def _request(self, method, path, json_body=None, params=None):
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
                    json=json_body,
                    params=params,
                    headers={
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                )

                try:
                    data = response.json()
                except Exception:
                    data = response.text

                if response.is_error:
                    return None, f"T212 DEMO API error {response.status_code}: {data}"

                return data, None

        except Exception as exc:
            return None, (
                f"T212 DEMO connection error: "
                f"{type(exc).__name__}: {exc}"
            )

    async def _submit_market(
        self,
        side,
        ticker,
        quantity,
        extended_hours=False,
        __event_emitter__=None,
    ):
        quantity = float(quantity)

        if quantity <= 0:
            return "Quantity must be greater than zero."

        fingerprint = (
            side,
            ticker,
            round(quantity, 8),
            bool(extended_hours),
        )

        now = time.monotonic()

        if (
            fingerprint == self.last_submission
            and now - self.last_submission_time < 30
        ):
            return (
                "DUPLICATE BLOCKED: identical DEMO order submitted "
                "less than 30 seconds ago."
            )

        signed_quantity = quantity if side == "BUY" else -quantity

        payload = {
            "ticker": ticker,
            "quantity": signed_quantity,
            "extendedHours": bool(extended_hours),
        }

        if __event_emitter__:
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {
                        "description": (
                            f"Submitting T212 DEMO {side}: "
                            f"{ticker} x {quantity}"
                        ),
                        "done": False,
                    },
                }
            )

        # Mark before POST because T212 market-order POST is non-idempotent.
        self.last_submission = fingerprint
        self.last_submission_time = now

        data, error = await self._request(
            "POST",
            "/equity/orders/market",
            json_body=payload,
        )

        if error:
            return error

        if __event_emitter__:
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {
                        "description": "T212 DEMO accepted the order request.",
                        "done": True,
                    },
                }
            )

        return self._show(
            {
                "environment": "DEMO",
                "action": side,
                "ticker": ticker,
                "quantity": quantity,
                "extendedHours": bool(extended_hours),
                "broker_response": data,
            }
        )

    async def pipe(self, body: dict, __event_emitter__=None):
        messages = body.get("messages", [])

        if not messages:
            return "No command supplied."

        command = str(messages[-1].get("content", "")).strip()

        if command.upper() == "HELP":
            return (
                "T212 DEMO Trading Gateway v0.3.1\n\n"
                "DASHBOARD\n"
                "ACCOUNT\n"
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
                "One controlled broker gateway. DEMO only."
            )

        if command.upper() == "ACCOUNT":
            data, error = await self._request(
                "GET",
                "/equity/account/summary",
            )
            return error or self._show(data)

        if command.upper() == "DASHBOARD":
            account, error = await self._request(
                "GET",
                "/equity/account/summary",
            )
            if error:
                return error

            positions, error = await self._request(
                "GET",
                "/equity/positions",
            )
            if error:
                return error

            orders, error = await self._request(
                "GET",
                "/equity/orders",
            )
            if error:
                return error

            positions = positions if isinstance(positions, list) else []
            orders = orders if isinstance(orders, list) else []

            return self._show(
                {
                    "environment": "DEMO",
                    "gatewayVersion": "0.3.1",
                    "account": account,
                    "openPositionCount": len(positions),
                    "positions": positions,
                    "pendingOrderCount": len(orders),
                    "pendingOrders": orders,
                    "executionEnabled": True,
                    "liveTradingEnabled": False,
                }
            )

        match = re.fullmatch(
            r"FIND\s+(.+)",
            command,
            flags=re.IGNORECASE,
        )

        if match:
            query = match.group(1).strip().lower()

            data, error = await self._request(
                "GET",
                "/equity/metadata/instruments",
            )

            if error:
                return error

            matches = []

            for inst in data if isinstance(data, list) else []:
                haystack = " ".join(
                    str(inst.get(k, ""))
                    for k in ("ticker", "name", "shortName", "isin")
                ).lower()

                if query in haystack:
                    matches.append(
                        {
                            "name": inst.get("name"),
                            "shortName": inst.get("shortName"),
                            "ticker": inst.get("ticker"),
                            "currencyCode": inst.get("currencyCode"),
                            "type": inst.get("type"),
                            "extendedHours": inst.get("extendedHours"),
                            "maxOpenQuantity": inst.get("maxOpenQuantity"),
                        }
                    )

            if not matches:
                return (
                    "No T212 DEMO instrument matched "
                    f"'{match.group(1).strip()}'."
                )

            return self._show(matches[:10])

        if command.upper() == "POSITIONS":
            data, error = await self._request(
                "GET",
                "/equity/positions",
            )
            return error or self._show(data)

        match = re.fullmatch(
            r"POSITION\s+([A-Za-z0-9._-]+)",
            command,
            flags=re.IGNORECASE,
        )

        if match:
            ticker = match.group(1).upper()

            data, error = await self._request(
                "GET",
                "/equity/positions",
            )

            if error:
                return error

            positions = data if isinstance(data, list) else []
            filtered = [
                p for p in positions
                if str(p.get("ticker", "")).upper() == ticker
            ]

            return self._show(filtered)

        if command.upper() == "ORDERS":
            data, error = await self._request(
                "GET",
                "/equity/orders",
            )
            return error or self._show(data)

        match = re.fullmatch(
            r"ORDER\s+(\d+)",
            command,
            flags=re.IGNORECASE,
        )

        if match:
            data, error = await self._request(
                "GET",
                f"/equity/orders/{match.group(1)}",
            )
            return error or self._show(data)

        match = re.fullmatch(
            r"(BUY|SELL)(?:\s+(EXT))?\s+"
            r"([A-Za-z0-9._-]+)\s+"
            r"([0-9]+(?:\.[0-9]+)?)",
            command,
            flags=re.IGNORECASE,
        )

        if match:
            side = match.group(1).upper()
            extended = bool(match.group(2))
            ticker = match.group(3).upper()
            quantity = float(match.group(4))

            return await self._submit_market(
                side,
                ticker,
                quantity,
                extended,
                __event_emitter__,
            )

        match = re.fullmatch(
            r"CLOSE\s+([A-Za-z0-9._-]+)",
            command,
            flags=re.IGNORECASE,
        )

        if match:
            ticker = match.group(1).upper()

            data, error = await self._request(
                "GET",
                "/equity/positions",
            )

            if error:
                return error

            positions = data if isinstance(data, list) else []

            matching = [
                p for p in positions
                if str(p.get("ticker", "")).upper() == ticker
            ]

            if not matching:
                return f"No open DEMO position found for {ticker}."

            available = sum(
                float(p.get("quantityAvailableForTrading") or 0)
                for p in matching
            )

            if available <= 0:
                return f"No quantity available to close for {ticker}."

            return await self._submit_market(
                "SELL",
                ticker,
                available,
                False,
                __event_emitter__,
            )

        return "Command not recognised. Use HELP."

class Pipe(Tools):
    def __init__(self):
        super().__init__()

    async def _submit_market(self, side, ticker, quantity, extended_hours=False, __event_emitter__=None, intent_id=""):
        result = await self.place_market_order(side, ticker, quantity, extended_hours, intent_id)
        if __event_emitter__:
            state = json.loads(result).get("state", "UNKNOWN")
            await __event_emitter__({"type": "status", "data": {"description": "DEMO broker readback: " + state, "done": True}})
        return result

    async def pipe(self, body: dict, __event_emitter__=None):
        messages = body.get("messages", [])

        if not messages:
            return "No command supplied."

        command = str(messages[-1].get("content", "")).strip()

        if command.upper() == "HELP":
            return (
                "T212 DEMO Trading Gateway v0.4.0-candidate\n\n"
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
                "Append INTENT <decision-id> to BUY/SELL/CLOSE. Reuse it for retries. Omitted IDs permanently block identical repeats. DEMO only."
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
                    "gatewayVersion": "0.4.0-candidate",
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
            return await self.find_instrument(match.group(1).strip())

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
            r"([0-9]+(?:\.[0-9]+)?)(?:\s+INTENT\s+([A-Za-z0-9_.:-]{1,128}))?",
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
                match.group(5) or "",
            )

        match = re.fullmatch(
            r"CLOSE\s+([A-Za-z0-9._-]+)(?:\s+INTENT\s+([A-Za-z0-9_.:-]{1,128}))?",
            command,
            flags=re.IGNORECASE,
        )

        if match:
            return await self.close_position(match.group(1).upper(), match.group(2) or "")

        return "Command not recognised. Use HELP."

"""
title: Trading 212 DEMO Gateway
author: Katie / OpenAI
description: Single server-side Trading 212 DEMO broker toolkit for DeepSeek/Open WebUI agents.
version: 0.1.0
"""

import os
import json
import time
import httpx


class Tools:
    def __init__(self):
        self.base_url = "https://demo.trading212.com/api/v0"
        self.last_submission = None
        self.last_submission_time = 0.0

    def _credentials(self):
        return (
            os.getenv("T212_DEMO_API_KEY", "").strip(),
            os.getenv("T212_DEMO_API_SECRET", "").strip(),
        )

    def _show(self, value):
        if isinstance(value, str):
            return value
        return json.dumps(value, indent=2, default=str)

    async def _request(self, method, path, json_body=None):
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

    async def trading_dashboard(self) -> str:
        """
        Return the current Trading 212 DEMO account summary, open positions, pending orders,
        execution state and LIVE-disabled state. Use this before and after broker actions.
        :return: JSON text containing the current DEMO trading dashboard.
        """
        account, error = await self._request("GET", "/equity/account/summary")
        if error:
            return error

        positions, error = await self._request("GET", "/equity/positions")
        if error:
            return error

        orders, error = await self._request("GET", "/equity/orders")
        if error:
            return error

        positions = positions if isinstance(positions, list) else []
        orders = orders if isinstance(orders, list) else []

        return self._show(
            {
                "environment": "DEMO",
                "account": account,
                "openPositionCount": len(positions),
                "positions": positions,
                "pendingOrderCount": len(orders),
                "pendingOrders": orders,
                "executionEnabled": True,
                "liveTradingEnabled": False,
            }
        )

    async def find_instrument(self, query: str) -> str:
        """
        Search Trading 212's DEMO instrument catalogue and return exact broker tickers.
        Use this before execution when you only have a company name or ordinary market symbol.
        :param query: Company name, ordinary ticker symbol, ISIN, or partial instrument name.
        :return: Up to 10 matching Trading 212 DEMO instruments as JSON text.
        """
        query = query.strip().lower()
        if not query:
            return "Instrument query is empty."

        data, error = await self._request("GET", "/equity/metadata/instruments")
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
            return f"No T212 DEMO instrument matched '{query}'."

        return self._show(matches[:10])

    async def list_positions(self) -> str:
        """
        Return all currently open Trading 212 DEMO positions. Use for verification and monitoring.
        :return: Open DEMO positions as JSON text.
        """
        data, error = await self._request("GET", "/equity/positions")
        return error or self._show(data)

    async def list_orders(self) -> str:
        """
        Return pending Trading 212 DEMO orders. Use for execution verification and monitoring.
        :return: Pending DEMO orders as JSON text.
        """
        data, error = await self._request("GET", "/equity/orders")
        return error or self._show(data)

    async def size_quantity(
        self,
        account_amount: float,
        instrument_price: float,
        account_to_instrument_fx: float = 1.0,
        decimal_places: int = 4,
    ) -> str:
        """
        Convert a desired account-currency exposure into an approximate share quantity.
        This is calculation only and never places an order. The caller must supply a current
        market quote and, when currencies differ, a current account-currency-to-instrument-currency FX rate.
        :param account_amount: Desired exposure in the Trading 212 account currency, e.g. 10 for GBP 10.
        :param instrument_price: Current instrument price in the instrument's trading currency.
        :param account_to_instrument_fx: How many instrument-currency units equal one account-currency unit, e.g. GBPUSD 1.335 for GBP account buying USD stock.
        :param decimal_places: Number of decimal places to round the resulting quantity to.
        :return: JSON text with converted value and proposed quantity.
        """
        if account_amount <= 0 or instrument_price <= 0 or account_to_instrument_fx <= 0:
            return "All monetary inputs and FX must be greater than zero."

        decimal_places = max(0, min(int(decimal_places), 8))
        instrument_value = float(account_amount) * float(account_to_instrument_fx)
        raw_quantity = instrument_value / float(instrument_price)
        quantity = round(raw_quantity, decimal_places)

        return self._show(
            {
                "accountAmount": account_amount,
                "instrumentCurrencyValue": instrument_value,
                "instrumentPrice": instrument_price,
                "accountToInstrumentFx": account_to_instrument_fx,
                "quantity": quantity,
                "roundingDecimalPlaces": decimal_places,
                "note": "Approximate sizing only. Re-check current quote/FX before execution.",
            }
        )

    async def place_market_order(
        self,
        side: str,
        ticker: str,
        quantity: float,
        extended_hours: bool = False,
    ) -> str:
        """
        Place a Trading 212 DEMO market order through the single broker gateway.
        DEMO ONLY. Use only after the trading workflow has produced an explicit execution decision.
        Never retry this method blindly because Trading 212 market-order POST is non-idempotent.
        After this returns, call trading_dashboard or list_positions to verify the broker-side result.
        :param side: BUY or SELL.
        :param ticker: Exact Trading 212 internal ticker, such as AEMD_US_EQ.
        :param quantity: Positive share quantity. This method applies the sign required by T212.
        :param extended_hours: True only when intentionally submitting an extended-hours eligible order.
        :return: Broker response as JSON text.
        """
        side = side.strip().upper()
        ticker = ticker.strip().upper()
        quantity = float(quantity)

        if side not in ("BUY", "SELL"):
            return "Side must be BUY or SELL."

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

        payload = {
            "ticker": ticker,
            "quantity": quantity if side == "BUY" else -quantity,
            "extendedHours": bool(extended_hours),
        }

        self.last_submission = fingerprint
        self.last_submission_time = now

        data, error = await self._request(
            "POST",
            "/equity/orders/market",
            json_body=payload,
        )

        if error:
            return error

        return self._show(
            {
                "environment": "DEMO",
                "action": side,
                "ticker": ticker,
                "quantity": quantity,
                "extendedHours": bool(extended_hours),
                "brokerResponse": data,
                "verificationRequired": True,
                "liveTradingEnabled": False,
            }
        )

    async def close_position(self, ticker: str) -> str:
        """
        Close the full available quantity of one existing Trading 212 DEMO position.
        DEMO ONLY. This submits a market SELL and must be verified afterwards.
        :param ticker: Exact Trading 212 internal ticker of the position to close.
        :return: Broker response as JSON text.
        """
        ticker = ticker.strip().upper()

        data, error = await self._request("GET", "/equity/positions")
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

        return await self.place_market_order(
            side="SELL",
            ticker=ticker,
            quantity=available,
            extended_hours=False,
        )

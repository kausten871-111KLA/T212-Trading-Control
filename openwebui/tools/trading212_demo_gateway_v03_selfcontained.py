"""
title: Trading 212 DEMO Gateway
author: Katie / OpenAI
description: Single server-side Trading 212 DEMO broker toolkit for DeepSeek/Open WebUI agents.
version: 0.3.0-candidate
"""

import os
import json
import time
import asyncio
import random
from pathlib import Path
import httpx


class InstrumentCache:
    def __init__(
        self,
        cache_path="/app/backend/data/t212_instrument_cache.json",
        diff_path="/app/backend/data/t212_instrument_diff.json",
        ttl_seconds=86400,
    ):
        self.cache_path = Path(cache_path)
        self.diff_path = Path(diff_path)
        self.ttl_seconds = int(ttl_seconds)

    def load(self):
        if not self.cache_path.exists():
            return None
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and isinstance(payload.get("instruments"), list):
                return payload
        except Exception:
            return None
        return None

    def is_fresh(self, payload):
        if not payload:
            return False
        try:
            fetched_at = float(payload.get("fetchedAtEpoch", 0))
            return (time.time() - fetched_at) < self.ttl_seconds
        except Exception:
            return False

    def _write_json_atomic(self, path, payload):
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        temp.replace(path)

    def diff(self, previous, current):
        prev = {str(x.get("ticker")): x for x in previous if isinstance(x, dict) and x.get("ticker")}
        cur = {str(x.get("ticker")): x for x in current if isinstance(x, dict) and x.get("ticker")}

        added = [cur[t] for t in sorted(set(cur) - set(prev))]
        removed = [prev[t] for t in sorted(set(prev) - set(cur))]
        tracked = (
            "name","shortName","isin","currencyCode","type",
            "extendedHours","maxOpenQuantity",
        )
        changed = []
        for ticker in sorted(set(prev) & set(cur)):
            changes = {
                field: {"before": prev[ticker].get(field), "after": cur[ticker].get(field)}
                for field in tracked
                if prev[ticker].get(field) != cur[ticker].get(field)
            }
            if changes:
                changed.append({"ticker": ticker, "changes": changes})

        result = {
            "generatedAtEpoch": time.time(),
            "baselineWasPresent": bool(previous),
            "addedCount": len(added),
            "removedCount": len(removed),
            "changedCount": len(changed),
            "added": added,
            "removed": removed,
            "changed": changed,
        }
        if not previous:
            result["added"] = []
            result["addedCount"] = 0
        return result

    def save_snapshot(self, instruments, previous=None):
        previous = previous or []
        payload = {
            "provider": "Trading212",
            "environment": "DEMO",
            "fetchedAtEpoch": time.time(),
            "count": len(instruments),
            "instruments": instruments,
        }
        diff_payload = self.diff(previous, instruments)
        self._write_json_atomic(self.cache_path, payload)
        self._write_json_atomic(self.diff_path, diff_payload)
        return diff_payload

    def search(self, query, limit=10):
        payload = self.load()
        if not payload:
            return []
        needle = (query or "").strip().lower()
        if not needle:
            return []
        rows = []
        for inst in payload.get("instruments", []):
            haystack = " ".join(
                str(inst.get(k, ""))
                for k in ("ticker", "name", "shortName", "isin")
            ).lower()
            if needle in haystack:
                rows.append(inst)
                if len(rows) >= max(1, int(limit)):
                    break
        return rows

    def latest_diff(self):
        if not self.diff_path.exists():
            return {}
        try:
            return json.loads(self.diff_path.read_text(encoding="utf-8"))
        except Exception:
            return {}


class Tools:
    def __init__(self):
        self.base_url = "https://demo.trading212.com/api/v0"
        self.last_submission = None
        self.last_submission_time = 0.0
        self.instrument_cache = InstrumentCache()

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

        method = method.upper()
        max_attempts = 4 if method == "GET" else 1
        delay = 1.0

        for attempt in range(max_attempts):
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

                if method == "GET" and response.status_code == 429 and attempt + 1 < max_attempts:
                    retry_after = response.headers.get("Retry-After")
                    try:
                        wait = float(retry_after)
                    except Exception:
                        wait = delay + random.uniform(0, 0.25)
                    await asyncio.sleep(min(max(wait, 0.5), 15.0))
                    delay = min(delay * 2.0, 15.0)
                    continue

                if method == "GET" and 500 <= response.status_code < 600 and attempt + 1 < max_attempts:
                    await asyncio.sleep(delay + random.uniform(0, 0.25))
                    delay = min(delay * 2.0, 15.0)
                    continue

                if response.is_error:
                    return None, f"T212 DEMO API error {response.status_code}: {data}"

                return data, None

            except Exception as exc:
                if method == "GET" and attempt + 1 < max_attempts:
                    await asyncio.sleep(delay)
                    delay = min(delay * 2.0, 15.0)
                    continue
                return None, f"T212 DEMO connection error: {type(exc).__name__}: {exc}"

        return None, "T212 DEMO request failed."

    async def _ensure_instrument_cache(self, force=False):
        payload = self.instrument_cache.load()
        if payload and self.instrument_cache.is_fresh(payload) and not force:
            return payload["instruments"], None, "disk"

        previous = payload.get("instruments", []) if payload else []
        data, error = await self._request("GET", "/equity/metadata/instruments")
        if error:
            if previous:
                return previous, None, "stale-disk-fallback"
            return None, error, None

        instruments = data if isinstance(data, list) else []
        self.instrument_cache.save_snapshot(instruments, previous)
        return instruments, None, "api-refresh"

    async def refresh_instrument_cache(self, force: bool = False) -> str:
        """
        Read-only. Refresh or reuse the T212 DEMO instrument cache.
        """
        instruments, error, source = await self._ensure_instrument_cache(force=bool(force))
        if error:
            return error
        diff = self.instrument_cache.latest_diff()
        return self._show({
            "environment": "DEMO",
            "gatewayVersion": "0.3.0-candidate",
            "cacheSource": source,
            "instrumentCount": len(instruments or []),
            "diffSummary": {
                "baselineWasPresent": diff.get("baselineWasPresent"),
                "addedCount": diff.get("addedCount"),
                "removedCount": diff.get("removedCount"),
                "changedCount": diff.get("changedCount"),
            },
            "liveTradingEnabled": False,
        })

    async def instrument_cache_status(self) -> str:
        """
        Read-only. Report current T212 instrument cache state without a broker call.
        """
        payload = self.instrument_cache.load()
        return self._show({
            "environment": "DEMO",
            "gatewayVersion": "0.3.0-candidate",
            "cacheExists": bool(payload),
            "cacheFresh": self.instrument_cache.is_fresh(payload),
            "instrumentCount": len((payload or {}).get("instruments", [])),
            "fetchedAtEpoch": (payload or {}).get("fetchedAtEpoch"),
            "liveTradingEnabled": False,
        })

    async def new_on_t212(self, limit: int = 100) -> str:
        """
        Read-only. Return instruments added since the prior instrument snapshot.
        """
        limit = max(1, min(int(limit), 500))
        _, error, source = await self._ensure_instrument_cache(force=False)
        if error:
            return error
        diff = self.instrument_cache.latest_diff()
        added = diff.get("added", []) if isinstance(diff, dict) else []
        return self._show({
            "environment": "DEMO",
            "cacheSource": source,
            "baselineWasPresent": diff.get("baselineWasPresent"),
            "newCount": len(added),
            "newInstruments": added[:limit],
            "liveTradingEnabled": False,
        })

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
                "gatewayVersion": "0.3.0-candidate",
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
        Search the cached Trading 212 DEMO instrument catalogue and return exact broker tickers.
        The full instrument master is fetched at most once per cache TTL unless forced.
        """
        query = (query or "").strip()
        if not query:
            return "Instrument query is empty."

        _, error, source = await self._ensure_instrument_cache(force=False)
        if error:
            return error

        matches = self.instrument_cache.search(query, limit=10)
        if not matches:
            return f"No T212 DEMO instrument matched '{query}'."

        rows = []
        for inst in matches:
            rows.append({
                "name": inst.get("name"),
                "shortName": inst.get("shortName"),
                "ticker": inst.get("ticker"),
                "currencyCode": inst.get("currencyCode"),
                "type": inst.get("type"),
                "extendedHours": inst.get("extendedHours"),
                "maxOpenQuantity": inst.get("maxOpenQuantity"),
                "cacheSource": source,
            })
        return self._show(rows)

    async def recent_order_history(self, limit: int = 20) -> str:
        """
        Return recent historical Trading 212 DEMO orders for audit/reporting.
        Read-only. Uses the broker history endpoint and returns the first page only.
        :param limit: Number of recent history records requested, 1-50.
        :return: Historical DEMO orders as JSON text.
        """
        limit = max(1, min(int(limit), 50))
        data, error = await self._request(
            "GET",
            f"/equity/history/orders?limit={limit}",
        )
        return error or self._show(data)

    async def recent_transactions(self, limit: int = 20) -> str:
        """
        Return recent Trading 212 DEMO cash/account transactions for audit/reporting.
        Read-only. Uses the broker history endpoint and returns the first page only.
        :param limit: Number of recent transaction records requested, 1-50.
        :return: Historical DEMO transactions as JSON text.
        """
        limit = max(1, min(int(limit), 50))
        data, error = await self._request(
            "GET",
            f"/equity/history/transactions?limit={limit}",
        )
        return error or self._show(data)

    async def operations_dashboard(self, history_limit: int = 20) -> str:
        """
        Return a richer read-only Trading Operations dashboard:
        account, positions, pending orders, recent historical orders and recent transactions.
        DEMO only; never submits an order.
        :param history_limit: Number of order/transaction history rows requested, 1-50.
        :return: Consolidated broker-verified dashboard JSON text.
        """
        history_limit = max(1, min(int(history_limit), 50))

        account, error = await self._request("GET", "/equity/account/summary")
        if error:
            return error

        positions, error = await self._request("GET", "/equity/positions")
        if error:
            return error

        orders, error = await self._request("GET", "/equity/orders")
        if error:
            return error

        historical_orders, historical_orders_error = await self._request(
            "GET",
            f"/equity/history/orders?limit={history_limit}",
        )

        transactions, transactions_error = await self._request(
            "GET",
            f"/equity/history/transactions?limit={history_limit}",
        )

        positions = positions if isinstance(positions, list) else []
        orders = orders if isinstance(orders, list) else []

        return self._show(
            {
                "environment": "DEMO",
                "gatewayVersion": "0.3.0-candidate",
                "account": account,
                "openPositionCount": len(positions),
                "positions": positions,
                "pendingOrderCount": len(orders),
                "pendingOrders": orders,
                "recentOrderHistory": historical_orders,
                "recentOrderHistoryError": historical_orders_error,
                "recentTransactions": transactions,
                "recentTransactionsError": transactions_error,
                "executionEnabled": True,
                "liveTradingEnabled": False,
                "note": (
                    "Broker-verified read-only operational state. "
                    "History sections are first-page snapshots only."
                ),
            }
        )

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

"""
title: Trading 212 DEMO Gateway
author: Katie / OpenAI
description: Single server-side Trading 212 DEMO broker toolkit for DeepSeek/Open WebUI agents.
version: 0.4.0-candidate
"""

import os
import json
import time
import asyncio
import math
import re
import sqlite3
import hashlib
from email.utils import parsedate_to_datetime
from contextlib import contextmanager, asynccontextmanager
from pathlib import Path
import httpx

try:
    import fcntl
except ImportError:  # pragma: no cover - runtime is Linux
    fcntl = None


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
        self.lock_path = self.cache_path.with_suffix(".lock")

    @asynccontextmanager
    async def async_lock(self):
        """Wait without blocking the event loop, including across Tools instances."""
        if fcntl is None:
            raise RuntimeError("Shared cache locking requires Linux fcntl")
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.lock_path.open("a+")
        os.chmod(self.lock_path, 0o600)
        deadline = time.monotonic() + 180
        try:
            while True:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Instrument refresh lock timed out")
                    await asyncio.sleep(0.05)
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()

    @contextmanager
    def lock(self):
        """Serialise refreshes across Open WebUI workers and the host cache worker."""
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.lock_path.open("a+")
        os.chmod(self.lock_path, 0o600)
        try:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()

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
        os.chmod(temp, 0o600)
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

    def search(self, query, limit=10, currency_code="", working_schedule_id=0):
        payload = self.load()
        if not payload:
            return []
        needle = (query or "").strip().lower()
        if not needle:
            return []
        rows = []
        instruments = payload.get("instruments", [])
        exact = [i for i in instruments if str(i.get("ticker", "")).lower() == needle]
        for inst in exact or instruments:
            if currency_code and str(inst.get("currencyCode", "")).upper() != currency_code.upper():
                continue
            if working_schedule_id and inst.get("workingScheduleId") != working_schedule_id:
                continue
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


class OrderIntentJournal:
    """Durable at-most-one mutation attempt per explicit intent on shared local disk."""
    TERMINAL = {"FILLED", "CANCELLED", "CANCELED", "REJECTED", "EXPIRED"}

    def __init__(self, path):
        self.path = Path(path)

    @asynccontextmanager
    async def locked(self):
        if fcntl is None:
            raise RuntimeError("Order-intent locking requires Linux fcntl")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_suffix(".lock")
        handle = lock_path.open("a+")
        os.chmod(lock_path, 0o600)
        deadline = time.monotonic() + 180
        try:
            while True:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Order-intent lock timed out")
                    await asyncio.sleep(0.05)
            db = sqlite3.connect(str(self.path))
            os.chmod(self.path, 0o600)
            try:
                db.execute("PRAGMA synchronous=FULL")
                db.execute("CREATE TABLE IF NOT EXISTS intents (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL, broker_id TEXT, result TEXT NOT NULL)")
                db.execute("CREATE TABLE IF NOT EXISTS budget (id INTEGER PRIMARY KEY, last_attempt REAL NOT NULL)")
                db.commit()
                yield db
            finally:
                db.close()
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()

    @staticmethod
    def save(db, intent_id, state, result, broker_id=None):
        result = dict(result, intentId=intent_id, state=state, environment="DEMO", liveTradingEnabled=False)
        db.execute("UPDATE intents SET state=?,broker_id=COALESCE(?,broker_id),result=? WHERE id=?", (state, broker_id, json.dumps(result, default=str), intent_id))
        if state in OrderIntentJournal.TERMINAL and broker_id is not None:
            for other_id, encoded in db.execute("SELECT id,result FROM intents WHERE broker_id=? AND id!=?", (broker_id, intent_id)).fetchall():
                other = dict(json.loads(encoded), state=state, brokerResponse=result.get("brokerResponse"), verificationRequired=False, retryAllowed=False)
                db.execute("UPDATE intents SET state=?,result=? WHERE id=?", (state, json.dumps(other, default=str), other_id))
        db.commit()
        return result

    @staticmethod
    async def pace(db):
        row = db.execute("SELECT last_attempt FROM budget WHERE id=1").fetchone()
        wait = max(0, 2 - (time.time() - row[0])) if row else 0
        if wait:
            await asyncio.sleep(wait)
        db.execute("INSERT OR REPLACE INTO budget VALUES (1,?)", (time.time(),))
        db.commit()


class Tools:
    def __init__(self):
        self.base_url = "https://demo.trading212.com/api/v0"
        self.last_submission = None
        self.last_submission_time = 0.0
        self.instrument_cache = InstrumentCache(
            cache_path=os.getenv(
                "T212_INSTRUMENT_CACHE_PATH",
                "/app/backend/data/t212-scanner/t212_instrument_cache.json",
            ),
            diff_path=os.getenv(
                "T212_INSTRUMENT_DIFF_PATH",
                "/app/backend/data/t212-scanner/t212_instrument_diff.json",
            ),
            ttl_seconds=int(os.getenv("T212_INSTRUMENT_CACHE_TTL_SECONDS", "86400")),
        )
        self._cache_lock = asyncio.Lock()
        self._metadata_fetch_count = 0

    def _credentials(self):
        return (
            os.getenv("T212_DEMO_API_KEY", "").strip(),
            os.getenv("T212_DEMO_API_SECRET", "").strip(),
        )

    def _show(self, value):
        if isinstance(value, str):
            return value
        return json.dumps(value, indent=2, default=str)

    @staticmethod
    def _retry_delay(response, attempt):
        """Return a deterministic bounded GET retry delay in seconds."""
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            try:
                wait = float(retry_after)
                if math.isfinite(wait):
                    return max(wait, 0.5)
            except (TypeError, ValueError):
                try:
                    return max(parsedate_to_datetime(retry_after).timestamp() - time.time(), 0.5)
                except (TypeError, ValueError, OverflowError):
                    pass
        schedule = (1.0, 2.0, 4.0)
        return schedule[min(max(int(attempt), 0), len(schedule) - 1)]

    async def _request(self, method, path, json_body=None):
        if self.base_url != "https://demo.trading212.com/api/v0":
            return None, "DEMO endpoint required; LIVE and alternate bases are refused."
        key, secret = self._credentials()

        if not key or not secret:
            return None, "T212 DEMO credentials are not available to Open WebUI."

        method = method.upper()
        max_attempts = 4 if method == "GET" else 1
        for attempt in range(max_attempts):
            if method == "GET" and path == "/equity/metadata/instruments":
                self._metadata_fetch_count += 1
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
                    wait = self._retry_delay(response, attempt)
                    if path == "/equity/metadata/instruments":
                        wait = max(wait, 50.0)
                    if wait > 180:
                        return None, "Provider cooldown exceeds retry budget; no early retry."
                    await asyncio.sleep(wait)
                    continue

                if method == "GET" and 500 <= response.status_code < 600 and attempt + 1 < max_attempts:
                    await asyncio.sleep(self._retry_delay(response, attempt))
                    continue

                if response.is_error:
                    return None, f"T212 DEMO API error {response.status_code}: {data}"

                return data, None

            except Exception as exc:
                if method == "GET" and attempt + 1 < max_attempts:
                    await asyncio.sleep(self._retry_delay(None, attempt))
                    continue
                return None, f"T212 DEMO connection error: {type(exc).__name__}: {exc}"

        return None, "T212 DEMO request failed."

    async def _ensure_instrument_cache(self, force=False):
        # The asyncio lock prevents same-process coroutines from blocking the event
        # loop on flock while another coroutine awaits the metadata response.
        async with self._cache_lock:
            async with self.instrument_cache.async_lock():
                # Re-read after taking both locks; another process may have refreshed.
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
                if not instruments:
                    if previous:
                        return previous, None, "stale-disk-fallback"
                    return None, "T212 DEMO instrument metadata was empty.", None
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
            "gatewayVersion": "0.4.0-candidate",
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
            "gatewayVersion": "0.4.0-candidate",
            "cacheExists": bool(payload),
            "cacheFresh": self.instrument_cache.is_fresh(payload),
            "cachePath": str(self.instrument_cache.cache_path),
            "instrumentCount": len((payload or {}).get("instruments", [])),
            "fetchedAtEpoch": (payload or {}).get("fetchedAtEpoch"),
            "metadataFetchesThisProcess": self._metadata_fetch_count,
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

    async def find_instrument(self, query: str, currency_code: str = "", working_schedule_id: int = 0) -> str:
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

        matches = self.instrument_cache.search(query, limit=10, currency_code=currency_code, working_schedule_id=working_schedule_id)
        if not matches:
            return f"No T212 DEMO instrument matched '{query}'."

        rows = []
        for inst in matches:
            rows.append({
                "name": inst.get("name"),
                "shortName": inst.get("shortName"),
                "ticker": inst.get("ticker"),
                "currencyCode": inst.get("currencyCode"),
                "workingScheduleId": inst.get("workingScheduleId"),
                "selectionRequired": len(matches) > 1,
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
                "gatewayVersion": "0.4.0-candidate",
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

    def _order_journal(self):
        if self.base_url != "https://demo.trading212.com/api/v0":
            raise ValueError("DEMO endpoint required")
        key, secret = self._credentials()
        if not key or not secret:
            raise ValueError("DEMO credentials unavailable")
        namespace = hashlib.sha256(key.encode()).hexdigest()[:24]
        return OrderIntentJournal(self.instrument_cache.cache_path.parent / ("t212_order_intents_" + namespace + ".sqlite3"))

    @staticmethod
    def _positive(value, name):
        if isinstance(value, bool):
            raise ValueError(name + " must be a positive finite number")
        number = float(value)
        if not math.isfinite(number) or number <= 0:
            raise ValueError(name + " must be a positive finite number")
        return number

    async def _sell_capacity(self, db, ticker, quantity):
        positions, error = await self._request("GET", "/equity/positions")
        if error or not isinstance(positions, list):
            raise ValueError("Cannot verify broker holdings")
        orders, error = await self._request("GET", "/equity/orders")
        if error or not isinstance(orders, list):
            raise ValueError("Cannot verify existing sell reservations")
        def symbol(row):
            return row.get("ticker") or (row.get("instrument") or {}).get("ticker")
        matching = [p for p in positions if symbol(p) == ticker]
        available = sum(float(p.get("quantityAvailableForTrading", p.get("quantity", 0))) for p in matching)
        if any("quantityAvailableForTrading" not in p for p in matching):
            available -= sum(max(0, abs(float(o.get("quantity", 0))) - abs(float(o.get("filledQuantity", 0)))) for o in orders if symbol(o) == ticker and (str(o.get("side", "")).upper() == "SELL" or float(o.get("quantity", 0)) < 0))
        pending_ids = {str(o.get("id")) for o in orders}
        for encoded, state, broker_id in db.execute("SELECT payload,state,broker_id FROM intents"):
            local = json.loads(encoded)
            if state in OrderIntentJournal.TERMINAL or local.get("method") != "POST":
                continue
            body = local.get("body", {})
            if body.get("ticker") == ticker and body.get("quantity", 0) < 0 and (not broker_id or str(broker_id) not in pending_ids):
                available -= abs(body["quantity"])
        if not math.isfinite(available) or quantity > max(0, available) + 1e-9:
            raise ValueError("SELL exceeds verified unreserved holdings")

    async def _durable_mutation(self, intent_id, method, path, body):
        try:
            if not isinstance(intent_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", intent_id):
                raise ValueError("A stable explicit intent_id is required")
            journal = self._order_journal()
            payload = {"method": method, "path": path, "body": body}
            encoded = json.dumps(payload, sort_keys=True, allow_nan=False)
            fingerprint = hashlib.sha256(encoded.encode()).hexdigest()
            async with journal.locked() as db:
                previous = db.execute("SELECT fingerprint,result FROM intents WHERE id=?", (intent_id,)).fetchone()
                if previous:
                    if previous[0] != fingerprint:
                        raise ValueError("intent_id already identifies a different request")
                    return self._show(dict(json.loads(previous[1]), replayBlocked=True))
                if method == "POST" and body["quantity"] < 0:
                    await self._sell_capacity(db, body["ticker"], abs(body["quantity"]))
                if method == "DELETE":
                    existing, error = await self._request("GET", path)
                    if error or not isinstance(existing, dict):
                        raise ValueError("Cannot verify order before cancellation")
                    if str(existing.get("status", "")).upper() in OrderIntentJournal.TERMINAL:
                        return self._show({"state": existing["status"], "mutationAttempted": False, "brokerResponse": existing})
                # Commit the unresolved intent BEFORE transmission. A crash cannot authorize a replay.
                unresolved = {"state": "UNKNOWN", "intentId": intent_id, "verificationRequired": True, "environment": "DEMO", "liveTradingEnabled": False}
                db.execute("INSERT INTO intents VALUES (?,?,?,?,?,?)", (intent_id, fingerprint, encoded, "UNKNOWN", None, json.dumps(unresolved)))
                db.commit()
                await journal.pace(db)
                data, error = await self._request(method, path, json_body=body if method == "POST" else None)
                if error:
                    return self._show(journal.save(db, intent_id, "UNKNOWN", {"error": error, "verificationRequired": True, "retryAllowed": False}))
                broker_id = str(data.get("id")) if isinstance(data, dict) and data.get("id") is not None else None
                if method == "DELETE":
                    broker_id = path.rsplit("/", 1)[-1]
                if not broker_id:
                    return self._show(journal.save(db, intent_id, "UNKNOWN", {"brokerResponse": data, "verificationRequired": True, "retryAllowed": False}))
                journal.save(db, intent_id, "SUBMITTED", {"brokerResponse": data, "verificationRequired": True}, broker_id)
                verified, read_error = await self._request("GET", "/equity/orders/" + broker_id)
                state = str(verified.get("status", "UNKNOWN")).upper() if isinstance(verified, dict) else "UNKNOWN"
                # DELETE acceptance alone never means the order was cancelled or unfilled.
                return self._show(journal.save(db, intent_id, state, {"brokerOrderId": broker_id, "brokerResponse": verified, "readbackError": read_error, "verificationRequired": state not in OrderIntentJournal.TERMINAL, "retryAllowed": False}, broker_id))
        except (ValueError, TypeError, OverflowError) as exc:
            return self._show({"state": "VALIDATION_FAILED", "error": str(exc), "mutationAttempted": False, "environment": "DEMO", "liveTradingEnabled": False})

    async def _pending_order(self, kind, side, ticker, quantity, intent_id, time_validity, stop_price=None, limit_price=None):
        try:
            side = side.strip().upper()
            ticker = ticker.strip().upper()
            if side not in ("BUY", "SELL") or not re.fullmatch(r"[A-Z0-9][A-Z0-9_.-]{0,63}", ticker):
                raise ValueError("Valid BUY/SELL and exact broker ticker required")
            quantity = self._positive(quantity, "quantity")
            if time_validity not in ("DAY", "GOOD_TILL_CANCEL"):
                raise ValueError("time_validity must be DAY or GOOD_TILL_CANCEL")
            body = {"ticker": ticker, "quantity": quantity if side == "BUY" else -quantity, "timeValidity": time_validity}
            if kind in ("stop", "stop_limit"):
                body["stopPrice"] = self._positive(stop_price, "stop_price")
            if kind in ("limit", "stop_limit"):
                body["limitPrice"] = self._positive(limit_price, "limit_price")
            return await self._durable_mutation(intent_id, "POST", "/equity/orders/" + kind, body)
        except (ValueError, TypeError, AttributeError, OverflowError) as exc:
            return self._show({"state": "VALIDATION_FAILED", "error": str(exc), "mutationAttempted": False})

    async def place_stop_order(self, side: str, ticker: str, quantity: float, stop_price: float, intent_id: str, time_validity: str = "DAY") -> str:
        """Submit a DEMO STOP once per durable intent_id; read back broker status. Stops may slip."""
        return await self._pending_order("stop", side, ticker, quantity, intent_id, time_validity, stop_price=stop_price)

    async def place_limit_order(self, side: str, ticker: str, quantity: float, limit_price: float, intent_id: str, time_validity: str = "DAY") -> str:
        """Submit a DEMO LIMIT once per durable intent_id; acceptance is not a fill."""
        return await self._pending_order("limit", side, ticker, quantity, intent_id, time_validity, limit_price=limit_price)

    async def place_stop_limit_order(self, side: str, ticker: str, quantity: float, stop_price: float, limit_price: float, intent_id: str, time_validity: str = "DAY") -> str:
        """Submit a DEMO STOP_LIMIT once per durable intent_id; it can trigger without filling."""
        return await self._pending_order("stop_limit", side, ticker, quantity, intent_id, time_validity, stop_price=stop_price, limit_price=limit_price)

    async def cancel_order(self, order_id: int, intent_id: str) -> str:
        """Attempt DEMO cancellation once, then read status. A racing fill remains FILLED."""
        if isinstance(order_id, bool) or not isinstance(order_id, int) or order_id <= 0:
            return self._show({"state": "VALIDATION_FAILED", "mutationAttempted": False, "error": "Positive integer order_id required"})
        return await self._durable_mutation(intent_id, "DELETE", "/equity/orders/" + str(order_id), {})

    async def reconcile_order_intent(self, intent_id: str) -> str:
        """Read-only broker reconciliation for an existing intent; never resubmit an UNKNOWN mutation."""
        journal = self._order_journal()
        async with journal.locked() as db:
            row = db.execute("SELECT broker_id,result FROM intents WHERE id=?", (intent_id,)).fetchone()
            if not row:
                return self._show({"state": "NOT_FOUND", "retryAllowed": False})
            if not row[0]:
                return self._show(dict(json.loads(row[1]), reconciliation="Manual broker history/positions reconciliation required; no known broker ID", retryAllowed=False))
            data, error = await self._request("GET", "/equity/orders/" + row[0])
            if error or not isinstance(data, dict):
                return self._show(dict(json.loads(row[1]), readbackError=error, retryAllowed=False))
            state = str(data.get("status", "UNKNOWN")).upper()
            return self._show(journal.save(db, intent_id, state, {"brokerOrderId": row[0], "brokerResponse": data, "verificationRequired": state not in OrderIntentJournal.TERMINAL, "retryAllowed": False}, row[0]))

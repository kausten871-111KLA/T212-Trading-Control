"""
title: Trading 212 DEMO Gateway
author: Katie / OpenAI
description: Single server-side Trading 212 DEMO broker toolkit for DeepSeek/Open WebUI agents.
version: 0.2.1-cache-candidate
"""

import os
import json
import time
import httpx
import sqlite3
import hashlib
import uuid
import asyncio
import re
from contextlib import closing



# Cache ONLY broker instrument metadata; never account/position/order state.
class _MetadataCache:
    TTL = 600
    MIN_GAP = 55  # Broker publishes a 1 request / 50s catalogue budget.
    MAX_STALE = 86400

    def __init__(self, path=None):
        self.path = os.path.abspath(path or os.getenv(
            "T212_LEGACY_METADATA_CACHE_PATH",
            "/app/backend/data/t212-legacy-metadata.sqlite3"))

    def _connect(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        con = sqlite3.connect(self.path, timeout=10)
        con.execute("""CREATE TABLE IF NOT EXISTS metadata (
            scope TEXT PRIMARY KEY, payload TEXT, fetched REAL DEFAULT 0,
            earliest REAL DEFAULT 0, owner TEXT, lease_until REAL DEFAULT 0)""")
        con.execute("""CREATE TABLE IF NOT EXISTS read_budget (
            scope TEXT NOT NULL, route TEXT NOT NULL,
            earliest REAL NOT NULL DEFAULT 0, PRIMARY KEY(scope,route))""")
        con.commit()
        return con

    def reserve(self, scope, now):
        """SQLite serialisation prevents duplicate catalogue GETs across processes."""
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT OR IGNORE INTO metadata(scope) VALUES (?)",(scope,))
            raw, fetched, earliest, owner, lease_until = db.execute(
                "SELECT payload,fetched,earliest,owner,lease_until FROM metadata WHERE scope=?",
                (scope,)).fetchone()
            data = json.loads(raw) if raw is not None else None
            if data is not None and (not isinstance(data,list) or not all(isinstance(x,dict) for x in data)):
                raise ValueError("Damaged metadata cache must be preserved")
            age = max(0,now-fetched) if fetched else None
            if age is not None and age <= self.TTL:
                return "fresh",data,age,None,0
            if now < earliest or (owner and now < lease_until):
                wait=max(0,earliest-now,lease_until-now if owner else 0)
                return "waiting",data,age,None,wait
            lease=uuid.uuid4().hex
            db.execute("UPDATE metadata SET owner=?,lease_until=?,earliest=? WHERE scope=?",
                       (lease,now+45,now+self.MIN_GAP,scope))
            return "fetch",data,age,lease,0

    def complete(self,scope,lease,result=None,extra_delay=0):
        now=time.time()
        with closing(self._connect()) as db,db:
            db.execute("BEGIN IMMEDIATE")
            current=db.execute("SELECT owner FROM metadata WHERE scope=?",(scope,)).fetchone()
            if not current or current[0]!=lease:
                return False
            if result is not None:
                if not isinstance(result,list) or not result or not all(
                    isinstance(x,dict) and isinstance(x.get("ticker"),str) and x["ticker"]
                    for x in result
                ):
                    raise ValueError("Invalid catalogue; previous snapshot preserved")
                db.execute("UPDATE metadata SET payload=?,fetched=?,owner=NULL,lease_until=0,"
                           "earliest=MAX(earliest,?) WHERE scope=?",
                           (json.dumps(result,allow_nan=False),now,now+extra_delay,scope))
            else:
                db.execute("UPDATE metadata SET owner=NULL,lease_until=0,"
                           "earliest=MAX(earliest,?) WHERE scope=?",
                           (now+extra_delay,scope))
            return True

    def reserve_read(self,scope,route,gap,now):
        """Pace broker-truth reads; DO NOT cache account/position/order responses."""
        with closing(self._connect()) as db,db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT OR IGNORE INTO read_budget(scope,route) VALUES (?,?)",(scope,route))
            earliest=db.execute("SELECT earliest FROM read_budget WHERE scope=? AND route=?",
                                (scope,route)).fetchone()[0]
            wait=max(0,earliest-now)
            if wait>5:
                return wait,False
            db.execute("UPDATE read_budget SET earliest=? WHERE scope=? AND route=?",
                       (max(now,earliest)+gap,scope,route))
            return wait,True

    def defer_read(self,scope,route,seconds):
        with closing(self._connect()) as db,db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT OR IGNORE INTO read_budget(scope,route) VALUES (?,?)",(scope,route))
            db.execute("UPDATE read_budget SET earliest=MAX(earliest,?) WHERE scope=? AND route=?",
                       (time.time()+max(0,seconds),scope,route))

    @staticmethod
    def retry_delay(error):
        match=re.search(r"Retry-After:\s*(\d+(?:\.\d+)?)",error or "",re.I)
        return max(55,min(3600,float(match.group(1)))) if match else 55

class Tools:
    def __init__(self):
        self.base_url = "https://demo.trading212.com/api/v0"
        self.last_submission = None
        self.last_submission_time = 0.0
        self._metadata_cache = _MetadataCache()

    def _broker_scope(self, key):
        # T212 budgets apply per broker account, not per API key. Where multiple
        # keys share one account, configure the same non-secret account scope.
        account=os.getenv("T212_DEMO_ACCOUNT_SCOPE","").strip()
        return hashlib.sha256((self.base_url+":"+(account or key)).encode()).hexdigest()

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

        # Fresh broker truth: account reads are paced, never cached.
        read_gaps={"/equity/account/summary":5.5,
                   "/equity/positions":1.25,
                   "/equity/orders":5.5}
        budget_scope=None
        if method == "GET" and path in read_gaps:
            budget_scope=self._broker_scope(key)
            try:
                wait,reserved=await asyncio.to_thread(
                    self._metadata_cache.reserve_read,budget_scope,path,read_gaps[path],time.time())
                if not reserved:
                    return None, f"T212 DEMO GET paced; retry after {wait:.1f}s. No stale broker state returned."
                if wait:
                    await asyncio.sleep(wait)
            except (OSError,sqlite3.Error,ValueError) as exc:
                return None, f"T212 DEMO read budget unavailable ({type(exc).__name__}); no GET attempted."

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
                    header=response.headers.get("Retry-After","").strip()
                    delay=header if re.fullmatch(r"\d+(?:\.\d+)?",header) else ""
                    reset=response.headers.get("x-ratelimit-reset","").strip()
                    if not delay and re.fullmatch(r"\d+(?:\.\d+)?",reset):
                        delay=str(max(0,float(reset)-time.time()))
                    suffix=f" (Retry-After: {delay})" if delay else ""
                    if response.status_code == 429 and budget_scope:
                        try:
                            await asyncio.to_thread(self._metadata_cache.defer_read,
                                budget_scope,path,_MetadataCache.retry_delay(suffix))
                        except (OSError,sqlite3.Error,ValueError):
                            return None,"Broker GET throttled and cooldown persistence failed; stop repeated reads."
                    return None, f"T212 DEMO API error {response.status_code}{suffix}: {data}"

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
                "gatewayVersion": "0.2.1-cache-candidate",
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

        # Hash the credential key only to partition cache by DEMO API scope.
        key,secret=self._credentials()
        if not key or not secret:
            return "T212 DEMO credentials are not available to Open WebUI."
        scope=self._broker_scope(key)
        try:
            action,data,age,owner,wait=await asyncio.to_thread(
                self._metadata_cache.reserve,scope,time.time())
        except (OSError,sqlite3.Error,ValueError) as exc:
            return f"Metadata cache unavailable ({type(exc).__name__}); no broker GET attempted."
        stale=action=="waiting"
        if action=="fetch":
            incoming,error=await self._request("GET","/equity/metadata/instruments")
            try:
                valid=await asyncio.to_thread(
                    self._metadata_cache.complete,scope,owner,
                    incoming if error is None else None,
                    extra_delay=self._metadata_cache.retry_delay(error)
                    if error and "429" in error else 0)
            except (OSError,sqlite3.Error,ValueError) as exc:
                return f"Metadata persistence failed ({type(exc).__name__}); no verified result."
            if not valid:
                return "Metadata refresh lost its lease; retry, do not guess tickers."
            if error:
                stale=True
            else:
                data,age=incoming,0
        if stale and (age is None or age>self._metadata_cache.MAX_STALE or not data):
            return ("Instrument catalogue unavailable or refresh budget busy; "
                    f"wait approximately {int(wait)} seconds. Do not guess broker tickers.")
        if not isinstance(data,list):
            return "Invalid instrument metadata; broker ticker unverified."
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

        if stale:
            return self._show({"status":"STALE_RESEARCH_ONLY",
                "notExecutionVerified":True,"cacheAgeSeconds":int(age),
                "retryAfterSeconds":int(wait),"matches":matches[:10]})
        if not matches:
            return f"No T212 DEMO instrument matched '{query}'."
        return self._show(matches[:10])

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
                "gatewayVersion": "0.2.1-cache-candidate",
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

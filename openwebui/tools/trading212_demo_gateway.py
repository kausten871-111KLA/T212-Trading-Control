"""
title: Trading 212 DEMO Gateway
author: Katie / OpenAI
description: Single server-side Trading 212 DEMO broker toolkit for DeepSeek/Open WebUI agents.
version: 0.2.3-durable-market-intents-candidate
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
import math
from email.utils import parsedate_to_datetime
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
            for value in (fetched,earliest,lease_until):
                if not isinstance(value,(int,float)) or not math.isfinite(value) or value < 0:
                    raise ValueError("Invalid metadata timestamps")
            if fetched > now + 5:
                raise ValueError("Future metadata timestamp is unverified")
            data = json.loads(raw) if raw is not None else None
            if data is not None and (not isinstance(data,list) or not data or not all(
                isinstance(x,dict) and isinstance(x.get("ticker"),str) and x["ticker"] for x in data)):
                raise ValueError("Damaged metadata cache must be preserved")
            age = max(0,now-fetched) if fetched else None
            if age is not None and age <= self.TTL:
                return "fresh",data,age,None,0
            # Global 429 cooldown bridges metadata and fresh broker reads.
            global_row = db.execute("SELECT earliest FROM read_budget WHERE scope=? AND route=?", (scope,"*")).fetchone()
            global_deadline=global_row[0] if global_row else 0
            if not isinstance(global_deadline,(int,float)) or not math.isfinite(global_deadline) or global_deadline < 0:
                raise ValueError("Invalid durable account cooldown")
            earliest = max(earliest, global_deadline)
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
            global_row=db.execute("SELECT earliest FROM read_budget WHERE scope=? AND route=?",(scope,"*")).fetchone()
            global_deadline=global_row[0] if global_row else 0
            if not isinstance(global_deadline,(int,float)) or not math.isfinite(global_deadline) or global_deadline < 0:
                raise ValueError("Invalid durable account cooldown")
            if not isinstance(earliest,(int,float)) or not math.isfinite(earliest) or earliest < 0:
                raise ValueError("Invalid durable read budget")
            earliest=max(earliest,global_deadline)
            if not math.isfinite(earliest) or earliest < 0:
                raise ValueError("Invalid durable read budget")
            wait=max(0,earliest-now)
            if wait>5:
                return wait,False
            db.execute("UPDATE read_budget SET earliest=? WHERE scope=? AND route=?",
                       (max(now,earliest)+gap,scope,route))
            return wait,True

    def cooldown_remaining(self,scope,now):
        with closing(self._connect()) as db:
            row=db.execute("SELECT earliest FROM read_budget WHERE scope=? AND route=?",(scope,"*")).fetchone()
            if row and (not isinstance(row[0],(int,float)) or not math.isfinite(row[0]) or row[0] < 0):
                raise ValueError("Invalid durable account cooldown")
            return max(0,row[0]-now) if row else 0

    def defer_read(self,scope,route,seconds):
        with closing(self._connect()) as db,db:
            db.execute("BEGIN IMMEDIATE")
            deadline=time.time()+max(0,seconds)
            for target in (route,"*"):
                db.execute("INSERT OR IGNORE INTO read_budget(scope,route) VALUES (?,?)",(scope,target))
                db.execute("UPDATE read_budget SET earliest=MAX(earliest,?) WHERE scope=? AND route=?",
                           (deadline,scope,target))
            db.execute("UPDATE metadata SET earliest=MAX(earliest,?) WHERE scope=?",(deadline,scope))

    @staticmethod
    def retry_delay(error):
        match=re.search(r"Retry-After:\s*(\d+(?:\.\d+)?)",error or "",re.I)
        return max(55,float(match.group(1))) if match else 55


from pathlib import Path
from contextlib import asynccontextmanager
try:
    import fcntl
except ImportError:
    fcntl = None


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

        # Query/cursor changes never create another endpoint budget.
        route=path.split("?",1)[0]
        read_gaps={"/equity/account/summary":5.5,
                   "/equity/positions":1.25,
                   "/equity/orders":5.5,
                   "/equity/history/orders":10.5,
                   "/equity/history/transactions":10.5}
        budget_scope=self._broker_scope(key) if method == "GET" else None
        if budget_scope:
            try:
                if route in read_gaps:
                    wait,reserved=await asyncio.to_thread(
                        self._metadata_cache.reserve_read,budget_scope,route,read_gaps[route],time.time())
                    if not reserved:
                        return None, f"T212 DEMO GET paced; retry after {wait:.1f}s. No stale broker state returned."
                    if wait:
                        await asyncio.sleep(wait)
                # Recheck after waiting: another worker may have received 429.
                remaining=await asyncio.to_thread(self._metadata_cache.cooldown_remaining,budget_scope,time.time())
                if remaining:
                    return None, f"T212 DEMO GET account cooldown; retry after {remaining:.1f}s. No stale broker state returned."
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
                    delays=[]
                    header=response.headers.get("Retry-After", "").strip()
                    try:
                        seconds=float(header)
                    except ValueError:
                        try:
                            seconds=parsedate_to_datetime(header).timestamp()-time.time()
                        except (ValueError,TypeError,OverflowError):
                            seconds=0
                    if math.isfinite(seconds) and seconds>=0:
                        delays.append(seconds)
                    try:
                        reset=float(response.headers.get("x-ratelimit-reset", ""))-time.time()
                        if math.isfinite(reset) and reset>=0:
                            delays.append(reset)
                    except (ValueError,TypeError,OverflowError):
                        pass
                    delay=max(delays,default=0)
                    suffix=f" (Retry-After: {delay})" if delay else ""
                    if response.status_code == 429 and budget_scope:
                        try:
                            await asyncio.to_thread(self._metadata_cache.defer_read,
                                budget_scope,route,max(55,delay))
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

    def _order_journal(self):
        if self.base_url != "https://demo.trading212.com/api/v0":
            raise ValueError("DEMO endpoint required")
        key, secret = self._credentials()
        if not key or not secret:
            raise ValueError("DEMO credentials unavailable")
        namespace = hashlib.sha256(key.encode()).hexdigest()[:24]
        return OrderIntentJournal(Path(self._metadata_cache.path).parent / ("t212_order_intents_" + namespace + ".sqlite3"))

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
                        state = str(existing["status"]).upper()
                        result = journal.save(db, intent_id, state, {"mutationAttempted": False, "brokerResponse": existing, "verificationRequired": False, "retryAllowed": False}, path.rsplit("/", 1)[-1])
                        return self._show(result)
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

    async def place_market_order_with_intent(
        self, side: str, ticker: str, quantity: float, intent_id: str, extended_hours: bool = False
    ) -> str:
        """Submit a DEMO MARKET order using a caller-created stable intent ID.

        Different legitimate trading decisions must use distinct IDs. If submission
        returns UNKNOWN, query reconcile_order_intent; do not create another ID to
        replay the same decision. Existing place_market_order remains available.
        :param side: BUY or SELL.
        :param ticker: Exact T212 instrument identifier.
        :param quantity: Positive fractional/whole share quantity.
        :param intent_id: Unique immutable decision identifier, not a broker order ID.
        :param extended_hours: True if chosen and instrument eligible.
        :return: Recorded result and broker readback, when available.
        """
        try:
            if not isinstance(side, str) or not isinstance(ticker, str):
                raise ValueError("Valid BUY/SELL and exact T212 ticker required")
            direction=side.strip().upper()
            symbol=ticker.strip().upper()
            if direction not in ("BUY","SELL") or not re.fullmatch(r"[A-Z0-9][A-Z0-9_.-]{0,63}",symbol):
                raise ValueError("Valid BUY/SELL and exact T212 ticker required")
            qty=self._positive(quantity,"quantity")
            if not isinstance(extended_hours,bool):
                raise ValueError("extended_hours must be boolean")
            body={"ticker":symbol,"quantity":qty if direction=="BUY" else -qty,
                  "extendedHours":extended_hours}
            res=json.loads(await self._durable_mutation(
                intent_id,"POST","/equity/orders/market",body))
            res.update(action=direction,ticker=symbol,quantity=qty,
                       extendedHours=extended_hours)
            return self._show(res)
        except (ValueError,TypeError,AttributeError,OverflowError) as exc:
            return self._show({"state":"VALIDATION_FAILED","error":str(exc),
                               "mutationAttempted":False,"environment":"DEMO",
                               "liveTradingEnabled":False})

    async def close_position_with_intent(self,ticker: str,intent_id: str) -> str:
        """Close a verified DEMO position using a durable SELL intent.

        :param ticker: Exact T212 instrument identifier.
        :param intent_id: Stable unique close-decision identifier.
        :return: Submission and broker verification status.
        """
        if not isinstance(ticker,str) or not re.fullmatch(r"[A-Z0-9][A-Z0-9_.-]{0,63}",ticker.strip().upper()):
            return self._show({"state":"VALIDATION_FAILED","mutationAttempted":False,
                               "error":"Exact T212 ticker required"})
        symbol=ticker.strip().upper()
        positions,error=await self._request("GET","/equity/positions")
        if error:return error
        matches=[p for p in (positions if isinstance(positions,list) else [])
                 if (p.get("ticker") or (p.get("instrument") or {}).get("ticker","")).upper()==symbol]
        available=sum(float(p.get("quantityAvailableForTrading") or 0) for p in matches)
        if available<=0:return self._show({"state":"NO_POSITION","ticker":symbol,
                                           "mutationAttempted":False})
        return await self.place_market_order_with_intent(
            "SELL",symbol,available,intent_id,False)

"""DeepSeek-owned DEMO position monitor: durable exit conditions and one-shot dispatch.

Core only: broker adapter + process supervisor are separate deployables.
No stop levels, position caps, strategy decisions or timed closes are imposed.
"""
from __future__ import annotations
import asyncio
import json
import math
import os
import re
import sqlite3
import time
from pathlib import Path

VALID_OPERATORS = {"AT_OR_ABOVE", "AT_OR_BELOW"}
VALID_STATUSES = {"ACTIVE", "CLAIMED", "UNKNOWN", "ACKNOWLEDGED", "FILLED", "CANCELLED", "REJECTED", "EXPIRED"}
TICKER = re.compile(r"[A-Z0-9][A-Z0-9_.-]{0,63}\Z")
ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")

class MonitorError(ValueError):
    pass

def positive_number(value, name):
    if isinstance(value, bool):
        raise MonitorError(name + " must be a positive finite number")
    try:
        result = float(value)
    except (ValueError, TypeError) as exc:
        raise MonitorError(name + " must be a positive finite number") from exc
    if not math.isfinite(result) or result <= 0:
        raise MonitorError(name + " must be a positive finite number")
    return result

class MonitorLedger:
    """Shared process-safe store for decisions from DeepSeek and execution receipts."""
    def __init__(self, path):
        self.path = Path(path)

    def db(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path), timeout=30)
        os.chmod(self.path, 0o600)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("""CREATE TABLE IF NOT EXISTS watches (
            watch_id TEXT PRIMARY KEY, ticker TEXT NOT NULL, operator TEXT NOT NULL,
            price REAL NOT NULL, intent_id TEXT UNIQUE NOT NULL, strategy_version TEXT NOT NULL,
            state TEXT NOT NULL, last_price REAL, observed_at REAL,
            broker_receipt TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, watch_id TEXT NOT NULL, at REAL NOT NULL,
            kind TEXT NOT NULL, detail TEXT NOT NULL)""")
        conn.commit()
        return conn

    def register(self, watch_id, ticker, operator, price, intent_id, strategy_version):
        """Register an explicit DeepSeek trading decision, never an assistant-generated stop."""
        if not isinstance(watch_id,str) or not ID.fullmatch(watch_id):
            raise MonitorError("Stable watch_id required")
        if not isinstance(intent_id,str) or not ID.fullmatch(intent_id):
            raise MonitorError("Stable execution intent_id required")
        if not isinstance(ticker,str) or not TICKER.fullmatch(ticker):
            raise MonitorError("Exact broker ticker required")
        if operator not in VALID_OPERATORS:
            raise MonitorError("Unknown condition")
        level = positive_number(price, "price")
        if not isinstance(strategy_version,str) or not strategy_version.strip():
            raise MonitorError("DeepSeek strategy_version required")
        params=(ticker,operator,level,intent_id,strategy_version)
        db=self.db()
        try:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT * FROM watches WHERE watch_id=?",(watch_id,)).fetchone()
            if row:
                prior=(row["ticker"],row["operator"],row["price"],row["intent_id"],row["strategy_version"])
                if prior!=params: raise MonitorError("Existing watch cannot be silently rewritten")
                db.commit()
                return "EXISTING"
            now=time.time()
            db.execute("""INSERT INTO watches
                (watch_id,ticker,operator,price,intent_id,strategy_version,state,created_at,updated_at)
                VALUES (?,?,?,?,?,?,'ACTIVE',?,?)""",(watch_id,*params,now,now))
            db.execute("INSERT INTO events(watch_id,at,kind,detail) VALUES(?,?,?,?)",
                       (watch_id,now,"REGISTERED",json.dumps({"ticker":ticker,"condition":operator,
                        "price":level,"strategy_version":strategy_version})))
            db.commit()
            return "REGISTERED"
        except:
            db.rollback()
            raise
        finally:
            db.close()

    def cancel_active(self, watch_id):
        """DeepSeek can withdraw a queued condition before its order is claimed.

        An in-flight order must be reconciled or cancelled at the broker,
        never silently forgotten in the local store.
        """
        db=self.db()
        try:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT state FROM watches WHERE watch_id=?",(watch_id,)).fetchone()
            if not row:
                db.commit()
                return "NOT_FOUND"
            if row["state"]!="ACTIVE":
                db.commit()
                return "IN_FLIGHT_OR_TERMINAL"
            now=time.time()
            db.execute("UPDATE watches SET state='CANCELLED',updated_at=? WHERE watch_id=?",(now,watch_id))
            db.execute("INSERT INTO events(watch_id,at,kind,detail) VALUES(?,?,?,?)",
                       (watch_id,now,"CANCELLED",json.dumps({"reason":"controller_cancelled_active_watch"})))
            db.commit()
            return "CANCELLED"
        except:
            db.rollback();raise
        finally:
            db.close()

    def rows(self, states=("ACTIVE",)):
        db=self.db()
        try:
            mask=",".join("?" for _ in states)
            return [dict(r) for r in db.execute(
                "SELECT * FROM watches WHERE state IN ("+mask+") ORDER BY created_at,watch_id",tuple(states))]
        finally: db.close()

    def claim(self, watch_id, observed_price):
        price=positive_number(observed_price,"observed_price")
        db=self.db()
        try:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT * FROM watches WHERE watch_id=?",(watch_id,)).fetchone()
            if not row or row["state"]!="ACTIVE":
                db.commit();return False
            if not trigger(row["operator"],price,row["price"]):
                db.commit();return False
            now=time.time()
            db.execute("""UPDATE watches SET state='CLAIMED',last_price=?,observed_at=?,updated_at=?
                WHERE watch_id=? AND state='ACTIVE'""",(price,now,now,watch_id))
            db.execute("INSERT INTO events(watch_id,at,kind,detail) VALUES(?,?,?,?)",
                       (watch_id,now,"CLAIMED",json.dumps({"observed_price":price,"level":row["price"]})))
            db.commit()
            return True
        except:
            db.rollback();raise
        finally: db.close()

    def record(self, watch_id, state, receipt):
        if state not in VALID_STATUSES or state == "ACTIVE":
            raise MonitorError("Invalid result state")
        db=self.db()
        try:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT state FROM watches WHERE watch_id=?",(watch_id,)).fetchone()
            if row is None or row["state"] not in ("CLAIMED","UNKNOWN","ACKNOWLEDGED"):
                raise MonitorError("Only outstanding watch can receive a broker receipt")
            if state not in ("UNKNOWN","ACKNOWLEDGED","FILLED","REJECTED","CANCELLED","EXPIRED"):
                raise MonitorError("Unconfirmed state not accepted")
            now=time.time()
            db.execute("UPDATE watches SET state=?,broker_receipt=?,updated_at=? WHERE watch_id=?",
                       (state,json.dumps(receipt,sort_keys=True,default=str),now,watch_id))
            db.execute("INSERT INTO events(watch_id,at,kind,detail) VALUES(?,?,?,?)",
                       (watch_id,now,state,json.dumps(receipt,sort_keys=True,default=str)))
            db.commit()
        except:
            db.rollback();raise
        finally:db.close()

def trigger(operator,current,level):
    return current >= level if operator=="AT_OR_ABOVE" else current <= level

def normalized_receipt(payload):
    try:
        data=json.loads(payload) if isinstance(payload,str) else payload
    except json.JSONDecodeError:
        return ("UNKNOWN",{"error":"Unparseable broker result"})
    if not isinstance(data,dict):
        return ("UNKNOWN",{"error":"Broker result is not an object"})
    status=str(data.get("state",data.get("status","UNKNOWN"))).upper()
    if status in ("FILLED","CANCELLED","CANCELED","REJECTED","EXPIRED"):
        return ("CANCELLED" if status=="CANCELED" else status,data)
    if status in ("PENDING","PARTIAL","PARTIALLY_FILLED","SUBMITTED","NEW","ACKNOWLEDGED"):
        return ("ACKNOWLEDGED",data)
    return ("UNKNOWN",data)

def index_positions(positions):
    """Index exact broker identities; never choose between competing rows.

    A malformed unrelated row must not crash every controller watch. If a row
    names a valid ticker but also supplies malformed/conflicting identity data,
    keep that ticker ambiguous for the entire snapshot, regardless of row order.
    """
    indexed = {}
    ambiguous = set()
    for position in positions:
        if not isinstance(position, dict):
            continue
        top = position.get("ticker")
        instrument = position.get("instrument")
        malformed = instrument is not None and not isinstance(instrument, dict)
        nested = instrument.get("ticker") if isinstance(instrument, dict) else None
        identities = set()
        for value in (top, nested):
            if value is None:
                continue
            if not isinstance(value, str) or not TICKER.fullmatch(value):
                malformed = True
            else:
                identities.add(value)
        if malformed or len(identities) != 1:
            ambiguous.update(identities)
            continue
        ticker = next(iter(identities))
        if ticker in indexed:
            ambiguous.add(ticker)
        else:
            indexed[ticker] = position
    for ticker in ambiguous:
        indexed.pop(ticker, None)
    return indexed, ambiguous

async def monitor_once(ledger, position_provider, submit_exit, reconcile_intent):
    """Evaluate only controller-registered exit conditions against broker position prices.

    All three callbacks must communicate with T212 DEMO via its *single existing gateway*.
    submit_exit(ticker, available_quantity, stable_intent_id) must call the durable method.
    Without broker position/price evidence no exit order is sent.
    """
    outcome={"checked":0,"triggered":0,"submitted":0,"reconciled":0,"unavailable":[]}
    pending=ledger.rows(("CLAIMED","UNKNOWN","ACKNOWLEDGED"))
    for row in pending:
        # Broker reconciliation is always attempted before any new action.
        try:
            receipt=await reconcile_intent(row["intent_id"])
            state,data=normalized_receipt(receipt)
            ledger.record(row["watch_id"],state,data)
            outcome["reconciled"]+=1
        except Exception as exc:
            outcome["unavailable"].append({"watch_id":row["watch_id"],"reason":type(exc).__name__})
    active=ledger.rows(("ACTIVE",))
    if not active:return outcome
    try:
        positions=await position_provider()
    except Exception as exc:
        outcome["unavailable"].append({"source":"broker_positions","reason":type(exc).__name__})
        return outcome
    if not isinstance(positions,list):
        outcome["unavailable"].append({"source":"broker_positions","reason":"invalid_payload"})
        return outcome
    byticker,ambiguous=index_positions(positions)
    for row in active:
        outcome["checked"]+=1
        symbol=row["ticker"]
        if symbol in ambiguous:
            outcome["unavailable"].append({"watch_id":row["watch_id"],"reason":"ambiguous_position_ticker"})
            continue
        position=byticker.get(symbol)
        if not position:
            outcome["unavailable"].append({"watch_id":row["watch_id"],"reason":"position_not_confirmed"})
            continue
        raw=position.get("currentPrice")
        try:
            observed=positive_number(raw,"currentPrice")
            qty=positive_number(position.get("quantityAvailableForTrading"),"available_quantity")
        except MonitorError:
            outcome["unavailable"].append({"watch_id":row["watch_id"],"reason":"broker_price_or_quantity_unavailable"})
            continue
        if not trigger(row["operator"],observed,row["price"]):
            continue
        if not ledger.claim(row["watch_id"],observed):
            continue
        outcome["triggered"]+=1
        # Record the claim BEFORE the call. A restart cannot submit it twice.
        try:
            receipt=await submit_exit(symbol,qty,row["intent_id"])
            state,data=normalized_receipt(receipt)
            ledger.record(row["watch_id"],state,data)
            outcome["submitted"]+=1
        except Exception as exc:
            ledger.record(row["watch_id"],"UNKNOWN",{"error":type(exc).__name__})
            outcome["unavailable"].append({"watch_id":row["watch_id"],"reason":type(exc).__name__})
    return outcome


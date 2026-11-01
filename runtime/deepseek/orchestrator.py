# orchestrator.py — deterministic autonomous trading worker (v1)
# Author: DeepSeek Trading Operations (controller). Engineering wires the two seams.
# Governing principle: AI perceives/reasons; deterministic software enforces.
# GatewayAdapter + DataSource are SEAMS to be implemented against live tools.

import sqlite3, json, time, threading, logging, uuid
from functools import wraps
from dataclasses import dataclass, asdict, field
from typing import Optional

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    HAS_APSCHEDULER = True
except ImportError:
    HAS_APSCHEDULER = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("orchestrator")

def serialized(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self.lock:
            try:
                return method(self, *args, **kwargs)
            except Exception:
                self.conn.rollback()
                raise
    return call

class StateDB:
    def __init__(self, path="trading_state.db"):
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA busy_timeout=5000")

    @serialized
    def init_schema(self):
        import os
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, "schema.sql")) as f:
            self.conn.executescript(f.read())
        columns = {r[1] for r in self.conn.execute("PRAGMA table_info(event_queue)")}
        if "claim_token" not in columns:
            self.conn.execute("ALTER TABLE event_queue ADD COLUMN claim_token TEXT")
        self.conn.commit()

    @serialized
    def emit(self, event_type, payload, priority=50, correlation_id=None):
        cur = self.conn.execute(
            "INSERT INTO event_queue(event_type,payload,priority,correlation_id,created_at) VALUES(?,?,?,?,?)",
            (event_type, json.dumps(payload), priority, correlation_id, int(time.time()))
        )
        self.conn.commit()
        return cur.lastrowid

    @serialized
    def claim(self, worker_id, event_types, lease_ttl=60, limit=1):
        if not event_types or isinstance(event_types, str):
            raise ValueError("Explicit event types required")
        if lease_ttl <= 0 or limit < 1:
            raise ValueError("Positive lease and limit required")
        now = time.time()
        self.conn.execute("BEGIN IMMEDIATE")
        marks = ",".join("?" for _ in event_types)
        rows = self.conn.execute(
            "SELECT id FROM event_queue WHERE status='pending' AND "
            "(next_retry_at IS NULL OR next_retry_at<=?) AND event_type IN (" + marks + ") "
            "ORDER BY priority,id LIMIT ?", (now, *event_types, limit)).fetchall()
        claimed = []
        for r in rows:
            token = uuid.uuid4().hex
            self.conn.execute("UPDATE event_queue SET status='claimed',worker_id=?,claim_token=?,"
                "claimed_at=?,lease_expires_at=? WHERE id=?", (worker_id,token,now,now+lease_ttl,r['id']))
            claimed.append(dict(self.conn.execute("SELECT * FROM event_queue WHERE id=?",(r['id'],)).fetchone()))
        self.conn.commit()
        return claimed

    @serialized
    def complete(self, event_id, worker_id, claim_token):
        cur = self.conn.execute("UPDATE event_queue SET status='done' WHERE id=? AND status='claimed' "
            "AND worker_id=? AND claim_token=? AND lease_expires_at>?",
            (event_id, worker_id, claim_token, time.time()))
        self.conn.commit()
        return cur.rowcount == 1

    @serialized
    def fail(self, event_id, worker_id, claim_token, error):
        self.conn.execute("BEGIN IMMEDIATE")
        row = self.conn.execute("SELECT * FROM event_queue WHERE id=? AND status='claimed' "
            "AND worker_id=? AND claim_token=? AND lease_expires_at>?",
            (event_id,worker_id,claim_token,time.time())).fetchone()
        if row is None:
            self.conn.commit()
            return False
        attempts = row['attempts'] + 1
        self.conn.execute("UPDATE event_queue SET status=?,attempts=?,next_retry_at=?,last_error=?,"
            "worker_id=NULL,claim_token=NULL,lease_expires_at=NULL WHERE id=?",
            ('failed' if attempts >= row['max_attempts'] else 'pending',attempts,
             time.time()+2**attempts,error,event_id))
        self.conn.commit()
        return True

    @serialized
    def requeue_dead(self, event_types):
        """Reclaim only the event types owned by the calling worker role.

        Global recovery can reset another worker's EXECUTE_ORDER lease. That
        worker alone must reconcile potentially submitted broker intents.
        """
        if isinstance(event_types, (str, bytes)):
            raise ValueError("Explicit non-empty event types required")
        try:
            event_types = tuple(event_types)
        except TypeError as exc:
            raise ValueError("Explicit non-empty event types required") from exc
        if not event_types or any(not isinstance(t, str) or not t for t in event_types):
            raise ValueError("Explicit non-empty event types required")
        marks = ",".join("?" for _ in event_types)
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            cur = self.conn.execute(
                "UPDATE event_queue SET status=CASE WHEN attempts+1>=max_attempts "
                "THEN 'failed' ELSE 'pending' END,attempts=attempts+1,"
                "worker_id=NULL,claim_token=NULL,lease_expires_at=NULL "
                "WHERE status='claimed' AND lease_expires_at<=? AND event_type IN (" + marks + ")",
                (time.time(), *event_types))
            self.conn.commit()
            return cur.rowcount
        except Exception:
            self.conn.rollback()
            raise

    @serialized
    def prepare_intent(self, payload):
        """Persist immutable controller intent before crossing the gateway boundary."""
        values=(payload['ticker'],payload['side'],payload['quantity'],'MARKET')
        self.conn.execute("BEGIN IMMEDIATE")
        old=self.conn.execute("SELECT ticker,side,quantity,order_type FROM intent WHERE id=?",(payload['intent_id'],)).fetchone()
        if old:
            if tuple(old)!=values:
                raise ValueError("Intent payload conflict")
            self.conn.commit()
            return False
        self.conn.execute("INSERT INTO intent(id,ticker,side,quantity,order_type,status,created_at) VALUES(?,?,?,?,?,'DISPATCHING',?)",
            (payload['intent_id'],*values,int(time.time())))
        self.conn.commit()
        return True

    @serialized
    def await_verification(self, event):
        cur=self.conn.execute("UPDATE event_queue SET status='awaiting_verification' WHERE id=? AND status='claimed' AND worker_id=? AND claim_token=? AND lease_expires_at>?",
            (event['id'],event['worker_id'],event['claim_token'],time.time()))
        self.conn.commit()
        return cur.rowcount==1

    @serialized
    def upsert_order(self, broker_order_id, intent_id, ticker, side, qty, order_type, status, broker_receipt, filled_qty=0, limit_price=None, stop_price=None):
        if broker_order_id is None:
            self.conn.execute("INSERT INTO recovery_record(intent_id,recovery_type,state,detail,created_at) VALUES(?,?,?,?,?)",
                (intent_id, "BROKER_ID_UNRESOLVED", status, json.dumps(broker_receipt), int(time.time())))
            self.conn.commit()
            return
        self.conn.execute(
            'INSERT INTO "order"(broker_order_id,intent_id,ticker,side,quantity,filled_quantity,order_type,limit_price,stop_price,status,broker_receipt,created_at,readback_state) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(broker_order_id) DO UPDATE SET status=excluded.status, filled_quantity=excluded.filled_quantity, broker_receipt=excluded.broker_receipt',
            (broker_order_id, intent_id, ticker, side, qty, filled_qty, order_type, limit_price, stop_price, status, json.dumps(broker_receipt), int(time.time()), "unverified"))
        self.conn.commit()

    @serialized
    def upsert_position(self, ticker, qty, avg_entry, status="OPEN"):
        self.conn.execute("INSERT INTO position(ticker,quantity,avg_entry,opened_at,status) VALUES(?,?,?,?,?)", (ticker, qty, avg_entry, int(time.time()), status))
        self.conn.commit()

    @serialized
    def log_error(self, agent, error_type, message, event_id=None, context=None):
        self.conn.execute("INSERT INTO error_log(event_id,agent,error_type,message,context,created_at) VALUES(?,?,?,?,?,?)",
            (event_id, agent, error_type, message, json.dumps(context or {}), int(time.time())))
        self.conn.commit()

    @serialized
    def submit_controller_instruction(self, instruction_type, payload):
        cur = self.conn.execute("INSERT INTO controller_instruction(instruction_type,payload,status,issued_at) VALUES(?,?, 'issued', ?)",
            (instruction_type, json.dumps(payload), int(time.time())))
        self.conn.commit(); return cur.lastrowid

@dataclass
class OrderResult:
    broker_order_id: Optional[int]
    intent_id: str
    status: str
    filled_qty: float = 0.0
    avg_price: Optional[float] = None
    receipt: dict = field(default_factory=dict)

class GatewayAdapter:
    def dashboard(self): raise NotImplementedError
    def place_market(self, intent_id, ticker, side, qty): raise NotImplementedError
    def place_limit(self, intent_id, ticker, side, qty, price, tif="DAY"): raise NotImplementedError
    def place_stop(self, intent_id, ticker, side, qty, stop): raise NotImplementedError
    def cancel(self, intent_id, order_id): raise NotImplementedError
    def list_orders(self): raise NotImplementedError
    def list_positions(self): raise NotImplementedError
    def reconcile(self, intent_id): raise NotImplementedError

class DataSource:
    def movers(self, min_price=2.0, min_vol=500000, min_cap=100000000): raise NotImplementedError
    def quote(self, symbol): raise NotImplementedError

class Orchestrator:
    def __init__(self, db, gateway, data):
        self.db = db; self.gateway = gateway; self.data = data
        self.stop_event = threading.Event()

    def trigger_premarket(self): self.db.emit("PREMARKET_INGEST", {"date": time.strftime("%Y-%m-%d")}, priority=70)
    def trigger_open(self): self.db.emit("MARKET_OPEN", {"ts": int(time.time())}, priority=20)
    def trigger_midday(self): self.db.emit("MARKET_MIDDAY", {"ts": int(time.time())}, priority=40)
    def trigger_close(self): self.db.emit("MARKET_CLOSE", {"ts": int(time.time())}, priority=20)

    def worker_loop(self, worker_id, handler, event_types, poll=2.0, lease_ttl=60):
        while not self.stop_event.is_set():
            try:
                self.db.requeue_dead(event_types)
                for ev in self.db.claim(worker_id, event_types, lease_ttl=lease_ttl):
                    try:
                        result=handler(ev)
                        if result is False:
                            self.db.await_verification(ev)
                        else:
                            self.db.complete(ev["id"], worker_id, ev["claim_token"])
                    except Exception as e:
                        log.exception("worker %s failed event %s", worker_id, ev["id"])
                        self.db.fail(ev["id"], worker_id, ev["claim_token"], str(e))
            except Exception:
                log.exception("worker %s loop error", worker_id)
            self.stop_event.wait(poll)

    def handle_scout(self, ev):
        for m in self.data.movers()[:50]:
            self.db.emit("CANDIDATE_FOUND", m, priority=50)

    def handle_executor(self, ev):
        p=json.loads(ev['payload'])
        intent_id=p['intent_id']
        if self.db.prepare_intent(p):
            r=self.gateway.place_market(intent_id,p['ticker'],p['side'],p['quantity'])
        else:
            # Restart, duplicate event, or uncertain first submission: reconcile only.
            rec=self.gateway.reconcile(intent_id)
            r=OrderResult(rec.get('broker_order_id'),intent_id,rec.get('status','UNKNOWN'),receipt=rec.get('receipt',{}))
        self.db.upsert_order(r.broker_order_id,r.intent_id,p['ticker'],p['side'],p['quantity'],
            'MARKET',r.status,r.receipt,r.filled_qty)
        if r.status=='UNKNOWN':
            self.db.log_error('executor','VERIFICATION','Broker outcome unresolved',ev['id'],{'intent':intent_id})
            return False
        return True

    def run(self):
        # Existing OPEN/MIDDAY/CLOSE automations remain the phase authority.
        # No internal cron jobs: their UTC placeholders duplicated those jobs.
        log.info("Phase events must arrive through existing automations")
        routes = [("scout-1", self.handle_scout, ("PREMARKET_INGEST",)),
                  ("executor-1", self.handle_executor, ("EXECUTE_ORDER",))]
        for wid, handler, event_types in routes:
            threading.Thread(target=self.worker_loop, args=(wid, handler, event_types), daemon=True).start()
        try:
            while not self.stop_event.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop_event.set()

if __name__ == "__main__":
    db = StateDB(); db.init_schema()
    print("Orchestrator scaffold loaded. Wire GatewayAdapter + DataSource, then call run().")

"""Attach the existing WebUI scheduled executions to the durable phase ledger.

Only observes saved, completed WebUI automation runs. WebUI remains the sole
scheduler and model/broker executor. This service NEVER requests another model
completion, broker quote or order. No user-supplied automation IDs are trusted.
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import json
import sqlite3
import subprocess
import time

from .controller_ack import ControllerAcknowledgements
from .controller_phase_bridge import ControllerPhaseBridge, PHASE_BY_AUTOMATION
from .controller_worker import ControllerPhaseWorker
from .worker_supervisor import WorkerSupervisor

MODEL = "trading-operations--deepseek"
TOOL_IDS = frozenset(("trading_212_demo_gateway_tool", "market_data_gateway",
                      "contabo_command_bridge"))
T212_READ_OR_WRITE = frozenset((
    "trading_dashboard", "list_positions", "list_orders",
    "recent_order_history", "recent_transactions",
    "place_market_order", "place_market_order_with_intent",
    "place_limit_order", "place_stop_order", "place_stop_limit_order",
    "close_position", "close_position_with_intent",
    "cancel_order", "reconcile_order_intent", "operations_dashboard",
))
MARKET_FUNCTIONS = T212_READ_OR_WRITE | frozenset((
    "candidate_scan", "most_active", "top_movers", "snapshots",
    "latest_quotes", "market_clock", "health_check",
))

# This code executes exclusively *inside* the already-running WebUI container,
# reading only technical run metadata from its own SQLite file. No credentials,
# broker order args or user chat content are emitted.
WEBUI_SCAN = r'''
import json,sqlite3
from datetime import datetime
IDs = ("94493540-36ef-4ab9-a9fb-06665a038a50",
       "59f7e6a5-021c-4edd-92f3-dfa2f7e05f5f",
       "e73d6c8e-457f-42b3-8177-645e7743e2a8")
c=sqlite3.connect("file:/app/backend/data/webui.db?mode=ro",uri=True,timeout=8)
c.row_factory=sqlite3.Row
out=[]
for aid in IDs:
 a=c.execute("select id,user_id,name,is_active,data from automation where id=?",(aid,)).fetchone()
 if not a:continue
 data=json.loads(a["data"]) if isinstance(a["data"],str) else a["data"]
 model=c.execute("select user_id,meta from model where id=?",(data.get("model_id"),)).fetchone()
 meta=json.loads(model["meta"]) if model and isinstance(model["meta"],str) else (model["meta"] if model else {})
 ids=set((meta or {}).get("toolIds") or [])
 specs_ok=True
 for name,minimum in (("trading_212_demo_gateway_tool",17),
                      ("market_data_gateway",10),("contabo_command_bridge",1)):
  t=c.execute("select specs from tool where id=?",(name,)).fetchone()
  if not t:specs_ok=False;break
  spec=json.loads(t["specs"]) if isinstance(t["specs"],str) else t["specs"]
  if len(spec or [])<minimum:specs_ok=False;break
 valid=bool(a["is_active"] and model and a["user_id"]==model["user_id"]
            and data.get("model_id")=="trading-operations--deepseek"
            and {"trading_212_demo_gateway_tool","market_data_gateway",
                 "contabo_command_bridge"}<=ids and specs_ok)
 runs=c.execute("select id,chat_id,status,created_at from automation_run where automation_id=? order by created_at desc limit 12",(aid,)).fetchall()
 for r in runs:
  msg=c.execute("select id,model_id,done,output from chat_message where chat_id=? and role='assistant' order by created_at desc limit 1",(r["chat_id"],)).fetchone()
  messages=json.loads(msg["output"]) if msg and isinstance(msg["output"],str) else (msg["output"] if msg else [])
  calls=[x for x in (messages or []) if isinstance(x,dict) and x.get("type")=="function_call"]
  results={x.get("call_id") for x in (messages or []) if isinstance(x,dict) and x.get("type")=="function_call_output" and x.get("call_id")}
  matched=[x.get("name") for x in calls if x.get("call_id") in results]
  out.append({"run_id":r["id"],"automation_id":aid,"created_at":r["created_at"],
    "status":r["status"],"chat_id":r["chat_id"],"message_id":msg["id"] if msg else None,
    "assistant_done":bool(msg and msg["done"]),
    "model_match":bool(msg and msg["model_id"]=="trading-operations--deepseek"),
    "owner_and_tools_valid":valid,
    "tool_outputs_matched":len(matched),
    "executed_names":matched})
c.close()
print(json.dumps({"runs":out},separators=(",",":")))
'''

class VerifiedScheduledRunObserver:
    """One receipt per WebUI automation run; never submits orders or model calls."""

    def __init__(self, db, *, fetch=None):
        self.db = db
        self.fetch = fetch or self._fetch_webui

    def install_schema(self):
        with self.db.lock:
            self.db.conn.execute("""
                CREATE TABLE IF NOT EXISTS webui_run_observer (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    baseline_ns INTEGER NOT NULL
                )
            """)
            self.db.conn.execute("""
                CREATE TABLE IF NOT EXISTS webui_run_receipt (
                    run_id TEXT PRIMARY KEY,
                    automation_id TEXT NOT NULL,
                    chat_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    event_id INTEGER NOT NULL,
                    instruction_id INTEGER NOT NULL,
                    run_created_ns INTEGER NOT NULL,
                    market_date TEXT NOT NULL,
                    gateway_tool_results INTEGER NOT NULL,
                    broker_tool_results INTEGER NOT NULL,
                    total_tool_results INTEGER NOT NULL,
                    recorded_at INTEGER NOT NULL
                )
            """)
            self.db.conn.commit()

    @staticmethod
    def _fetch_webui():
        process = subprocess.run(
            ("docker", "exec", "open-webui", "python", "-c", WEBUI_SCAN),
            text=True, capture_output=True, timeout=16, check=False,
        )
        if process.returncode != 0:
            raise RuntimeError("WebUI DB probe failed: " + str(process.returncode))
        value=json.loads(process.stdout)
        if not isinstance(value,dict) or not isinstance(value.get("runs"),list):
            raise RuntimeError("Invalid WebUI DB response")
        return value["runs"]

    @staticmethod
    def _valid(record):
        if not isinstance(record,dict):
            return False
        if record.get("automation_id") not in PHASE_BY_AUTOMATION:
            return False
        if (record.get("status") != "success" or record.get("assistant_done") is not True
                or record.get("model_match") is not True
                or record.get("owner_and_tools_valid") is not True):
            return False
        if not all(isinstance(record.get(k),str) and record.get(k)
                   for k in ("run_id","chat_id","message_id")):
            return False
        if type(record.get("created_at")) is not int or record["created_at"] < 1_500_000_000_000_000_000:
            return False
        if type(record.get("tool_outputs_matched")) is not int or record["tool_outputs_matched"] < 0:
            return False
        if not isinstance(record.get("executed_names"),list):
            return False
        return all(isinstance(x,str) and x for x in record["executed_names"])

    def initialise_from_existing_runs(self):
        """Set an initial watermark to avoid replaying historical WebUI runs."""
        runs=self.fetch()
        high=max((r["created_at"] for r in runs if isinstance(r,dict)
                  and type(r.get("created_at")) is int),default=time.time_ns())
        # A watermark based on "now" prevents a completed historical run
        # accidentally being re-enqueued when no historical rows existed.
        high=max(high,time.time_ns())
        with self.db.lock:
            self.db.conn.execute(
                "INSERT OR IGNORE INTO webui_run_observer(singleton,baseline_ns) VALUES(1,?)",
                (high,),
            )
            self.db.conn.commit()
            row=self.db.conn.execute(
                "SELECT baseline_ns FROM webui_run_observer WHERE singleton=1"
            ).fetchone()
        return int(row[0])

    def _instruction(self, event_id):
        r=self.db.conn.execute(
            "SELECT controller_instruction_id FROM controller_result "
            "WHERE event_id=? AND kind='PHASE_DISPATCH'",(event_id,),
        ).fetchone()
        return r[0] if r else None

    def consume(self, *, worker=None):
        """One bounded poll; validates source, dispatches, ACKs once, no I/O to broker."""
        baseline=self.db.conn.execute(
            "SELECT baseline_ns FROM webui_run_observer WHERE singleton=1"
        ).fetchone()
        if not baseline:
            raise RuntimeError("Run observer must be seeded before activation")
        records=sorted(
            (r for r in self.fetch() if self._valid(r)
             and r["created_at"] > baseline[0]),key=lambda r:r["created_at"],
        )
        worker=worker or ControllerPhaseWorker(self.db,WorkerSupervisor(self.db))
        counts={"eligible":len(records),"recorded":0,"duplicates":0,"gateway_verified":0}
        for run in records:
            if self.db.conn.execute("SELECT 1 FROM webui_run_receipt WHERE run_id=?",
                                    (run["run_id"],)).fetchone():
                counts["duplicates"]+=1
                continue
            market_date=datetime.fromtimestamp(
                run["created_at"]/1e9,timezone.utc
            ).astimezone(ZoneInfo("America/New_York")).date().isoformat()
            host_principal=object()
            allowed=lambda principal,aid: principal is host_principal and aid==run["automation_id"]
            event_id, _ = ControllerPhaseBridge(self.db, allowed).enqueue(
                automation_id=run["automation_id"],market_date=market_date,
                principal=host_principal)
            worker.run_once()
            instruction_id=self._instruction(event_id)
            if not instruction_id:
                raise RuntimeError("Controller phase dispatch did not produce an instruction")
            names=run["executed_names"]
            gateway_tools=len([n for n in names if n in MARKET_FUNCTIONS])
            broker_tools=len([n for n in names if n in T212_READ_OR_WRITE])
            outcome={
                "kind":"webui_host_verified_existing_schedule",
                "run_id":run["run_id"],
                "chat_id":run["chat_id"],
                "message_id":run["message_id"],
                "automation_id":run["automation_id"],
                "terminal":"completed",
                "gateway_tool_results":gateway_tools,
                "broker_tool_results":broker_tools,
                "total_tool_results":run["tool_outputs_matched"],
                "no_duplicate_model_invocation":True,
            }
            ack=ControllerAcknowledgements(self.db,allowed)
            current=ack.status(instruction_id=instruction_id,principal=host_principal)
            if current["receipt_id"]:
                # A manually re-run phase on the same market date should not
                # displace the receipt for the first authoritative run.
                counts["duplicates"]+=1
                continue
            ack.acknowledge(instruction_id=instruction_id,
                            principal=host_principal,outcome=outcome)
            with self.db.lock:
                self.db.conn.execute(
                    "INSERT OR IGNORE INTO webui_run_receipt "
                    "(run_id,automation_id,chat_id,message_id,event_id,instruction_id,"
                    "run_created_ns,market_date,gateway_tool_results,broker_tool_results,"
                    "total_tool_results,recorded_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (run["run_id"],run["automation_id"],run["chat_id"],run["message_id"],
                     event_id,instruction_id,run["created_at"],market_date,
                     gateway_tools,broker_tools,run["tool_outputs_matched"],int(time.time())),
                )
                self.db.conn.commit()
            counts["recorded"]+=1
            counts["gateway_verified"]+=int(gateway_tools>0)
        return counts

    def evidence(self):
        row=self.db.conn.execute(
            "SELECT count(*),coalesce(sum(gateway_tool_results>0),0),"
            "coalesce(sum(broker_tool_results>0 AND recorded_at>=?),0),"
            "max(recorded_at) FROM webui_run_receipt"
            ,(int(time.time())-86400,)
        ).fetchone()
        return {"completed_runs_recorded":row[0],
                "runs_using_t212_or_market_data":row[1],
                "recent_broker_runs":row[2],
                "last_recorded_at":row[3],
                "webui_schedule_connected":row[0]>0}

"""Offline receipt-ledger integration: no model, broker or external API calls."""
import tempfile
import time
import unittest
from pathlib import Path
from runtime.deepseek.orchestrator import StateDB
from runtime.deepseek.worker_supervisor import WorkerSupervisor
from runtime.deepseek.controller_dispatch import ControllerPhaseDispatcher
from runtime.deepseek.controller_ack import ControllerAcknowledgements
from runtime.deepseek.webui_run_observer import VerifiedScheduledRunObserver, PHASE_BY_AUTOMATION


class WebUIRunLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db=StateDB(str(Path(self.tmp.name)/"trading_state.db"))
        self.addCleanup(self.db.conn.close)
        self.db.init_schema()
        WorkerSupervisor(self.db).install_schema()
        ControllerPhaseDispatcher(self.db).install_schema()
        ControllerAcknowledgements(self.db,lambda p,a:True).install_schema()
        self.records=[]
        self.observer=VerifiedScheduledRunObserver(self.db,fetch=lambda:list(self.records))
        self.observer.install_schema()
        self.baseline=self.observer.initialise_from_existing_runs()

    def test_future_completed_broker_run_produces_single_ack(self):
        aid=list(PHASE_BY_AUTOMATION)[0]
        row={"run_id":"completed-run-a",
             "automation_id":aid,"created_at":self.baseline+2000000000,
             "chat_id":"chat_1","message_id":"message_1","status":"success",
             "assistant_done":True,"model_match":True,"owner_and_tools_valid":True,
             "tool_outputs_matched":3,
             "executed_names":["trading_dashboard","list_positions","candidate_scan"]}
        self.records=[row]
        got=self.observer.consume()
        self.assertEqual(got["recorded"],1)
        self.assertEqual(got["gateway_verified"],1)
        check=self.observer.evidence()
        self.assertEqual(check["completed_runs_recorded"],1)
        event=self.db.conn.execute("SELECT status FROM event_queue").fetchone()
        self.assertEqual(event[0],"done")
        instr=self.db.conn.execute("SELECT status FROM controller_instruction").fetchone()
        self.assertEqual(instr[0],"acknowledged")
        r=self.db.conn.execute("SELECT broker_tool_results,total_tool_results FROM webui_run_receipt").fetchone()
        self.assertEqual(tuple(r),(2,3))
        again=self.observer.consume()
        self.assertEqual(again["recorded"],0)
        self.assertEqual(again["duplicates"],1)
        self.assertEqual(self.db.conn.execute("SELECT count(*) FROM controller_instruction").fetchone()[0],1)

    def test_unfinished_or_unowned_run_is_never_emitted(self):
        aid=list(PHASE_BY_AUTOMATION)[0]
        record={"run_id":"not-done","automation_id":aid,
                "created_at":self.baseline+3000000000,
                "chat_id":"chat","message_id":"msg","status":"success",
                "assistant_done":False,"model_match":True,
                "owner_and_tools_valid":True,
                "tool_outputs_matched":1,"executed_names":["trading_dashboard"]}
        self.records=[record]
        self.assertEqual(self.observer.consume()["recorded"],0)
        self.assertEqual(self.db.conn.execute("SELECT count(*) FROM event_queue").fetchone()[0],0)
        record["assistant_done"]=True
        record["owner_and_tools_valid"]=False
        self.assertEqual(self.observer.consume()["recorded"],0)

    def test_baseline_skips_old_runs(self):
        aid=list(PHASE_BY_AUTOMATION)[0]
        self.records=[{"run_id":"old","automation_id":aid,
            "created_at":self.baseline-1,"chat_id":"chat","message_id":"msg",
            "status":"success","assistant_done":True,"model_match":True,
            "owner_and_tools_valid":True,"tool_outputs_matched":1,
            "executed_names":["trading_dashboard"]}]
        self.assertEqual(self.observer.consume()["recorded"],0)

    def test_second_same_day_run_does_not_produce_duplicate_controller_ack(self):
        aid=list(PHASE_BY_AUTOMATION)[0]
        def make(n):
            return {"run_id":"run"+str(n),"automation_id":aid,
             "created_at":self.baseline+1000000000*n,
             "chat_id":"chat"+str(n),"message_id":"msg"+str(n),
             "status":"success","assistant_done":True,"model_match":True,
             "owner_and_tools_valid":True,"tool_outputs_matched":1,
             "executed_names":["trading_dashboard"]}
        self.records=[make(2),make(3)]
        got=self.observer.consume()
        self.assertEqual(got["recorded"],1)
        self.assertEqual(got["duplicates"],1)
        self.assertEqual(self.db.conn.execute("SELECT count(*) FROM controller_instruction").fetchone()[0],1)

if __name__=="__main__":
    unittest.main()

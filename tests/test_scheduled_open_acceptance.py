"""Offline regressions for read-only scheduled-run trace acceptance."""
import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path

MODULE = (Path(__file__).resolve().parents[1] / "deploy" / "deepseek"
          / "webui_tool_binding" / "scheduled_open_acceptance.py")
spec = importlib.util.spec_from_file_location("scheduled_open_acceptance", MODULE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class ScheduledOpenAcceptanceTests(unittest.TestCase):
    def test_timestamp_ns_and_s(self):
        self.assertEqual(mod.utc_time(1792416904211116857).year, 2026)
        self.assertEqual(mod.utc_time(1792416904).year, 2026)

    def test_broker_output_correlates_by_call_id(self):
        entries = [
            {"type": "function_call", "call_id": "ok", "name": "trading_dashboard"},
            {"type": "function_call", "call_id": "missing", "name": "candidate_scan"},
            {"type": "function_call_output", "call_id": "ok", "output": []},
        ]
        got = mod.summarise_output(entries)
        self.assertEqual(got["tool_outputs_recorded"], {"trading_dashboard": 1})
        self.assertEqual(got["tool_calls"], {"trading_dashboard": 1, "candidate_scan": 1})
        self.assertEqual(got["output_missing_count"], 1)

    def test_irrelevant_functions_not_misclassified(self):
        data = [{"type": "function_call", "call_id": "a", "name": "view_skill"},
                {"type": "function_call_output", "call_id": "a"}]
        self.assertFalse(mod.summarise_output(data)["tool_outputs_recorded"])

    def test_empty_trace_has_no_false_positive(self):
        got = mod.summarise_output([])
        self.assertEqual(got["all_function_calls"], 0)
        self.assertEqual(got["tool_outputs_recorded"], {})

    def test_pending_with_preserved_three_automations(self):
        with tempfile.TemporaryDirectory() as t:
            path = str(Path(t) / "test.db")
            c = sqlite3.connect(path)
            c.execute("CREATE TABLE automation(id TEXT,name TEXT,is_active INTEGER,"
                      "last_run_at INTEGER,next_run_at INTEGER,user_id TEXT,data TEXT)")
            c.execute("CREATE TABLE automation_run(id TEXT,automation_id TEXT,"
                      "chat_id TEXT,status TEXT,created_at INTEGER)")
            c.execute("CREATE TABLE chat_message(chat_id TEXT,role TEXT,created_at INTEGER,"
                      "output TEXT,done INTEGER,model_id TEXT)")
            c.execute("CREATE TABLE model(id TEXT,user_id TEXT,meta TEXT)")
            c.execute("INSERT INTO model VALUES (?,?,?)", (
                "trading-operations--deepseek","principal",
                '{"toolIds":["market_data_gateway","trading_212_demo_gateway_tool"]}'))
            for number,name in enumerate(("US OPEN - DEMO","US MIDDAY - DEMO","US CLOSE - DEMO")):
                c.execute("INSERT INTO automation VALUES (?,?,?,NULL,NULL,?,?)",(
                    str(number),name,1,"principal",'{"model_id":"trading-operations--deepseek"}'))
            c.commit()
            pending = mod.report(path,"2026-10-20","US OPEN","Europe/London")["checks"][0]
            self.assertEqual(pending["run"], "PENDING")
            self.assertTrue(pending["model_tool_ids_present"])
            self.assertTrue(pending["model_owner_matches"])
            c.execute("INSERT INTO automation_run VALUES ('1','0','chat1','success',?)",
                      (1792499705841012000,))
            c.execute("INSERT INTO chat_message VALUES (?,?,?,?,?,?)",(
                "chat1","assistant",1792499705841012000,
                '[{"type":"function_call","call_id":"x","name":"trading_dashboard"},'
                '{"type":"function_call_output","call_id":"x","output":[]}]',1,
                "trading-operations--deepseek"))
            c.commit()
            result=mod.report(path,"2026-10-20","US OPEN","Europe/London")["checks"][0]
            self.assertEqual(result["run"],"RECORDED")
            self.assertEqual(result["tool_acceptance"],
                             "PASS_FUNCTION_CALLED_AND_OUTPUT_RECORDED")
            c.close()


if __name__ == "__main__":
    unittest.main()

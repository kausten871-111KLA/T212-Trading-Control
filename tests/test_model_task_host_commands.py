"""Offline host endpoint contract: never accepts model-claimed authentication."""
import tempfile
import unittest
from pathlib import Path
from runtime.deepseek.model_task_host_commands import dispatch_model_task

NOW="2026-10-23T13:00:00Z"

class HostModelTaskTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=Path(self.tmp.name)/"ledger.sqlite3"
        self.payload={"action":"create","payload":{
            "job_kind":"analysis","instruction":"Analyse current watchlist",
            "scheduled_at_utc":NOW,"dedupe_key":"analysis:20261023:1"}}

    def tearDown(self):
        self.tmp.cleanup()

    def call(self,payload=None,verified=True):
        return dispatch_model_task(self.payload if payload is None else payload,
                                   verified=verified,db_path=self.db)

    def test_create_durable(self):
        r=self.call()
        self.assertTrue(r["created"])
        self.assertEqual(r["model_id"],"trading-operations--deepseek")
        self.assertEqual(self.call()["task_id"],r["task_id"])

    def test_token_verification_mandatory(self):
        with self.assertRaises(PermissionError):
            self.call(verified=False)

    def test_model_claim_rejected(self):
        p={**self.payload,"model_id":"trading-operations--deepseek"}
        with self.assertRaises(ValueError):
            self.call(payload=p)

    def test_no_arbitrary_operation(self):
        with self.assertRaises(ValueError):
            self.call(payload={"action":"shell","payload":{"command":"id"}})

    def test_status_and_cancel(self):
        tid=self.call()["task_id"]
        q={"action":"status","payload":{"task_id":tid}}
        self.assertEqual(self.call(q)["state"],"pending")
        c={"action":"cancel","payload":{"task_id":tid}}
        self.assertEqual(self.call(c)["state"],"cancelled")
        self.assertEqual(self.call(q)["state"],"cancelled")

    def test_reject_broker_task(self):
        p={"action":"create","payload":{**self.payload["payload"],"job_kind":"place_order"}}
        with self.assertRaises(ValueError):
            self.call(p)

    def test_reject_secret_or_principal_field(self):
        p={"action":"create","payload":{**self.payload["payload"],"principal":"admin"}}
        with self.assertRaises(ValueError):
            self.call(p)

    def test_reject_unauthorized_model_override(self):
        p={"action":"create","payload":{**self.payload["payload"],"model_id":"deepseek-v4-pro"}}
        with self.assertRaises(ValueError):
            self.call(p)

    def test_reject_incomplete_request(self):
        with self.assertRaises(ValueError):
            self.call({"action":"create"})

if __name__=="__main__":
    unittest.main()

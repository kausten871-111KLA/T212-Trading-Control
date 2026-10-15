"""Full-source read-budget recovery acceptance. Synthetic transport, no broker calls."""
import asyncio
import ast
import importlib.util
import json
import sqlite3
import tempfile
import time
import unittest
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "openwebui/tools/trading212_demo_gateway.py"
spec = importlib.util.spec_from_file_location("legacy_full_source_recovery", SOURCE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
CATALOGUE = [{"ticker": "ACME_US_EQ", "name": "ACME", "currencyCode": "USD", "type": "STOCK"}]


class Response:
    def __init__(self, status=200, data=None, headers=None):
        self.status_code = status
        self.is_error = status >= 400
        self.headers = headers or {}
        self.data = data if data is not None else {"fresh": True}
        self.text = json.dumps(self.data)

    def json(self):
        return self.data


class ReadRecovery(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = patch.dict("os.environ", {
            "T212_LEGACY_METADATA_CACHE_PATH": str(Path(self.tmp.name) / "cache.sqlite"),
            "T212_DEMO_ACCOUNT_SCOPE": "synthetic-demo-account",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.sent = []
        self.responses = []
        outer = self

        class Client:
            def __init__(self, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def request(self, method, url, **kwargs):
                outer.sent.append((method, url, kwargs.get("json")))
                if not outer.responses:
                    raise AssertionError("Unexpected extra broker request")
                return outer.responses.pop(0)

        self.transport = patch.object(module.httpx, "AsyncClient", Client)
        self.transport.start()
        self.addCleanup(self.transport.stop)

    def tool(self, key="synthetic-key-A"):
        tool = module.Tools()
        tool._credentials = lambda: (key, "synthetic-secret")
        return tool

    async def test_metadata_429_blocks_account_positions_orders_and_history_across_keys(self):
        self.responses = [Response(429, {"error": "throttle"}, {"Retry-After": "120"})]
        await self.tool().find_instrument("ACME")
        other = self.tool("synthetic-key-B")
        for path in ("/equity/account/summary", "/equity/positions", "/equity/orders",
                     "/equity/history/orders?limit=20", "/equity/history/transactions?limit=50"):
            data, error = await other._request("GET", path)
            self.assertIsNone(data)
            self.assertIsNotNone(error)
        self.assertEqual(len(self.sent), 1)

    async def test_account_429_blocks_cold_metadata_after_tool_restart(self):
        self.responses = [Response(429, {"error": "throttle"}, {"Retry-After": "120"})]
        await self.tool()._request("GET", "/equity/account/summary")
        out = await self.tool("synthetic-key-B").find_instrument("ACME")
        self.assertNotIn("ACME_US_EQ", out)
        self.assertEqual(len(self.sent), 1)

    async def test_history_queries_share_endpoint_budget(self):
        self.responses = [Response(data={"items": []})]
        first, error = await self.tool()._request("GET", "/equity/history/orders?limit=1")
        second, error2 = await self.tool()._request("GET", "/equity/history/orders?limit=50&cursor=next")
        self.assertIsNone(error)
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertIsNotNone(error2)
        self.assertEqual(len(self.sent), 1)

    async def test_http_date_retry_after_is_persisted_across_routes(self):
        date = format_datetime(datetime.fromtimestamp(time.time() + 180, timezone.utc), usegmt=True)
        self.responses = [Response(429, {"error": "throttle"}, {"Retry-After": date})]
        await self.tool()._request("GET", "/equity/orders")
        data, error = await self.tool()._request("GET", "/equity/positions")
        self.assertIsNone(data)
        self.assertIsNotNone(error)
        self.assertEqual(len(self.sent), 1)

    async def test_cached_fresh_metadata_remains_available_during_account_cooldown(self):
        self.responses = [Response(data=CATALOGUE), Response(429, {"error": "throttle"}, {"Retry-After": "120"})]
        first = await self.tool().find_instrument("ACME")
        await self.tool()._request("GET", "/equity/account/summary")
        second = await self.tool().find_instrument("ACME")
        self.assertEqual(json.loads(first), json.loads(second))
        self.assertEqual(len(self.sent), 2)

    async def test_market_post_does_not_retry_or_acquire_read_budget(self):
        self.responses = [Response(429, {"error": "throttle"}, {"Retry-After": "120"})]
        out = await self.tool().place_market_order("BUY", "ACME_US_EQ", 0.5)
        self.assertIn("429", out)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0][0], "POST")
        self.assertEqual(self.sent[0][2]["quantity"], 0.5)

    async def test_queued_read_rechecks_new_account_cooldown_after_wait(self):
        tool = self.tool()
        scope = tool._broker_scope("synthetic-key-A")
        tool._metadata_cache.reserve_read(scope, "/equity/positions", 1.25, time.time())
        async def intervening_429(wait):
            tool._metadata_cache.defer_read(scope, "/equity/orders", 120)
        with patch.object(module.asyncio, "sleep", intervening_429):
            data, error = await tool._request("GET", "/equity/positions")
        self.assertIsNone(data)
        self.assertIn("cooldown", error)
        self.assertEqual(self.sent, [])

    async def test_long_retry_after_is_not_truncated(self):
        self.responses = [Response(429, {}, {"Retry-After": "7200"})]
        await self.tool()._request("GET", "/equity/positions")
        tool = self.tool()
        remaining = tool._metadata_cache.cooldown_remaining(tool._broker_scope("synthetic-key-A"), time.time())
        self.assertGreater(remaining, 7100)

    async def test_invalid_future_metadata_timestamp_fails_closed(self):
        self.responses = [Response(data=CATALOGUE)]
        tool = self.tool()
        await tool.find_instrument("ACME")
        with sqlite3.connect(tool._metadata_cache.path) as db:
            db.execute("UPDATE metadata SET fetched=?", (time.time() + 3600,))
        result = await self.tool().find_instrument("ACME")
        self.assertIn("unavailable", result)
        self.assertEqual(len(self.sent), 1)

    async def test_damaged_account_budget_fails_closed_and_preserves_data(self):
        tool = self.tool()
        scope = tool._broker_scope("synthetic-key-A")
        tool._metadata_cache.defer_read(scope, "/equity/orders", 120)
        with sqlite3.connect(tool._metadata_cache.path) as db:
            db.execute("UPDATE read_budget SET earliest='damaged' WHERE route='*'")
        data, error = await self.tool()._request("GET", "/equity/positions")
        self.assertIsNone(data)
        self.assertIn("unavailable", error)
        self.assertEqual(self.sent, [])
        with sqlite3.connect(tool._metadata_cache.path) as db:
            self.assertEqual(db.execute("SELECT earliest FROM read_budget WHERE route='*'").fetchone()[0], "damaged")

    async def test_original_order_and_read_method_asts_are_unchanged(self):
        original = Path(__file__).with_name("legacy_original.py.fixture")
        def methods(path):
            tree = ast.parse(path.read_text())
            cls = next(x for x in tree.body if isinstance(x, ast.ClassDef) and x.name == "Tools")
            return {x.name: ast.dump(x, include_attributes=False) for x in cls.body
                    if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef))}
        before, after = methods(original), methods(SOURCE)
        for name in ("place_market_order", "close_position", "_credentials", "size_quantity",
                     "list_positions", "list_orders", "recent_order_history", "recent_transactions"):
            self.assertEqual(before[name], after[name], name)


if __name__ == "__main__":
    unittest.main()

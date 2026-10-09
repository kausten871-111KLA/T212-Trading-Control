import asyncio
import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path


try:
    import httpx  # noqa: F401
except ModuleNotFoundError:
    httpx_stub = types.ModuleType("httpx")
    httpx_stub.AsyncClient = object
    httpx_stub.BasicAuth = object
    sys.modules["httpx"] = httpx_stub

MODULE = Path(__file__).with_name("trading212_demo_gateway_v03_selfcontained.py")
if not MODULE.exists():
    MODULE = Path(__file__).parents[1] / "openwebui" / "tools" / "trading212_demo_gateway_v03_selfcontained.py"
SPEC = importlib.util.spec_from_file_location("gateway_v03", MODULE)
GATEWAY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATEWAY)


class _Response:
    def __init__(self, retry_after=None):
        self.headers = {}
        if retry_after is not None:
            self.headers["Retry-After"] = retry_after


class GatewayCacheAcceptanceTests(unittest.IsolatedAsyncioTestCase):
    def _tool(self, directory, ttl=86400):
        tool = GATEWAY.Tools()
        tool.instrument_cache = GATEWAY.InstrumentCache(
            cache_path=str(Path(directory) / "t212_instrument_cache.json"),
            diff_path=str(Path(directory) / "t212_instrument_diff.json"),
            ttl_seconds=ttl,
        )
        return tool

    async def test_ten_fresh_lookups_fetch_metadata_once_and_never_post(self):
        instruments = [
            {
                "ticker": "ACME_US_EQ",
                "name": "Acme Holdings",
                "shortName": "Acme",
                "isin": "TEST00000001",
                "currencyCode": "USD",
                "type": "STOCK",
            }
        ]
        calls = []

        async def fake_request(method, path, json_body=None):
            calls.append((method, path, json_body))
            return instruments, None

        with tempfile.TemporaryDirectory() as td:
            tool = self._tool(td)
            tool._request = fake_request
            results = [
                json.loads(await tool.find_instrument("Acme"))
                for _ in range(50)
            ]

            metadata = [
                call for call in calls
                if call[0] == "GET" and call[1] == "/equity/metadata/instruments"
            ]
            self.assertEqual(len(metadata), 1)
            self.assertFalse(any(call[0] == "POST" for call in calls))
            self.assertEqual(results[0][0]["cacheSource"], "api-refresh")
            self.assertTrue(all(result[0]["ticker"] == "ACME_US_EQ" for result in results))
            self.assertTrue(all(result[0]["cacheSource"] == "disk" for result in results[1:]))
            self.assertEqual(os.stat(tool.instrument_cache.cache_path).st_mode & 0o777, 0o600)
            self.assertEqual(os.stat(tool.instrument_cache.lock_path).st_mode & 0o777, 0o600)

    async def test_concurrent_lookups_share_one_refresh(self):
        instruments = [{"ticker": "ABC_US_EQ", "name": "ABC", "type": "STOCK"}]
        calls = 0

        async def fake_request(method, path, json_body=None):
            nonlocal calls
            calls += 1
            await asyncio.sleep(0)
            return instruments, None

        with tempfile.TemporaryDirectory() as td:
            tool = self._tool(td)
            tool._request = fake_request
            await asyncio.gather(*(tool.find_instrument("ABC") for _ in range(10)))
            self.assertEqual(calls, 1)

    async def test_independent_tool_instances_share_refresh_without_deadlocking(self):
        calls = []
        async def request(method, path, json_body=None):
            calls.append((method, path))
            await asyncio.sleep(0.03)
            return [{"ticker":"ABC_US_EQ","name":"ABC"}], None
        with tempfile.TemporaryDirectory() as td:
            tools = [self._tool(td) for _ in range(10)]
            for tool in tools: tool._request = request
            await asyncio.wait_for(asyncio.gather(*(tool.find_instrument('ABC') for tool in tools)), 3)
            self.assertEqual(len(calls), 1)

    async def test_stale_cache_is_used_after_bounded_provider_failure(self):
        instruments = [{"ticker": "SAFE_US_EQ", "name": "Safe Corp", "type": "STOCK"}]

        async def unavailable(method, path, json_body=None):
            return None, "T212 DEMO API error 429: rate limited"

        with tempfile.TemporaryDirectory() as td:
            tool = self._tool(td, ttl=1)
            tool.instrument_cache.save_snapshot(instruments, [])
            payload = tool.instrument_cache.load()
            payload["fetchedAtEpoch"] = 1
            tool.instrument_cache._write_json_atomic(tool.instrument_cache.cache_path, payload)
            tool._request = unavailable

            result = json.loads(await tool.find_instrument("Safe"))
            self.assertEqual(result[0]["ticker"], "SAFE_US_EQ")
            self.assertEqual(result[0]["cacheSource"], "stale-disk-fallback")

    async def test_exact_ticker_currency_and_schedule_disambiguation(self):
        with tempfile.TemporaryDirectory() as td:
            tool=self._tool(td)
            tool.instrument_cache.save_snapshot([
                {'ticker':'ACME_US_EQ','name':'Acme','currencyCode':'USD','workingScheduleId':1},
                {'ticker':'ACME_GB_EQ','name':'Acme','currencyCode':'GBP','workingScheduleId':2}],[])
            async def forbidden(*args,**kwargs):raise AssertionError('Warm lookup made network request')
            tool._request=forbidden
            broad=json.loads(await tool.find_instrument('Acme'))
            self.assertTrue(all(row['selectionRequired'] for row in broad))
            selected=json.loads(await tool.find_instrument('Acme',currency_code='GBP',working_schedule_id=2))
            self.assertEqual([r['ticker'] for r in selected],['ACME_GB_EQ'])
            exact=json.loads(await tool.find_instrument('ACME_US_EQ'))
            self.assertEqual([r['ticker'] for r in exact],['ACME_US_EQ'])

    def test_retry_schedule_is_deterministic_and_bounded(self):
        self.assertEqual(
            [GATEWAY.Tools._retry_delay(None, i) for i in range(4)],
            [1.0, 2.0, 4.0, 4.0],
        )
        self.assertEqual(GATEWAY.Tools._retry_delay(_Response("9"), 0), 9.0)
        self.assertEqual(GATEWAY.Tools._retry_delay(_Response("99"), 0), 99.0)
        self.assertEqual(GATEWAY.Tools._retry_delay(_Response("bad"), 1), 2.0)


if __name__ == "__main__":
    unittest.main()

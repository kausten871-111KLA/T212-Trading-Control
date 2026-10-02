import json
import os
import unittest
from unittest.mock import patch

import sys
import types
import importlib.util
from pathlib import Path
from urllib.parse import urlencode, urlsplit, parse_qsl

# Offline transport double: the execution workspace has no httpx installation.
# These tests verify gateway request/response behaviour, not httpx integration.
class MockResponse:
    def __init__(self, status, json):
        self.status_code = status
        self.is_error = status >= 400
        self.payload = json
    def json(self):
        return self.payload

class MockURL(str):
    @property
    def params(self):
        return dict(parse_qsl(urlsplit(self).query))

class MockClient:
    def __init__(self, transport=None, **kwargs):
        self.handler = transport
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        pass
    async def get(self, url, params, headers):
        return self.handler(types.SimpleNamespace(method="GET", url=MockURL(url + "?" + urlencode(params)), headers=headers))

httpx = types.ModuleType("httpx")
httpx.AsyncClient = MockClient
httpx.MockTransport = lambda handler: handler
httpx.Response = MockResponse
source_path = Path(__file__).resolve().parents[1] / "openwebui/tools/market_data_gateway.py"
if not source_path.is_file():
    # Scratch candidate layout only; repository tests use the path above.
    source_path = Path(__file__).resolve().with_name("market_data_gateway.py")
spec = importlib.util.spec_from_file_location("_market_news_gateway_under_test", source_path)
gateway_under_test = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {"httpx": httpx}):
    spec.loader.exec_module(gateway_under_test)
Tools = gateway_under_test.Tools


class NewsTests(unittest.IsolatedAsyncioTestCase):
    async def call(self, response, status=200, **query):
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(status, json=response)
        client_type = httpx.AsyncClient
        with patch.dict(os.environ, {"ALPACA_API_KEY": "test-key", "ALPACA_API_SECRET": "test-secret"}), patch.object(
            httpx, "AsyncClient",
            side_effect=lambda **kwargs: client_type(transport=httpx.MockTransport(handler), **kwargs),
        ):
            result = json.loads(await Tools().news(**query))
        return result, calls

    async def test_metadata_only_single_read_and_existing_credentials(self):
        result, calls = await self.call({"news": [{"id": 1, "headline": "Example", "content": "hidden", "summary": "hidden", "created_at": "2026-10-02T12:00:00Z"}], "next_page_token": "next"}, symbols_csv="aapl,AAPL,nvda", limit=100)
        self.assertTrue(result["available"])
        self.assertEqual(result["nextPageToken"], "next")
        self.assertNotIn("content", result["news"][0])
        self.assertNotIn("summary", result["news"][0])
        self.assertEqual(len(calls), 1)
        request = calls[0]
        self.assertEqual(request.method, "GET")
        self.assertEqual(str(request.url).split("?")[0], "https://data.alpaca.markets/v1beta1/news")
        self.assertEqual(request.url.params["symbols"], "AAPL,NVDA")
        self.assertEqual(request.url.params["limit"], "50")
        self.assertEqual(request.url.params["include_content"], "false")
        self.assertEqual(request.headers["APCA-API-KEY-ID"], "test-key")
        self.assertNotIn("test-secret", json.dumps(result))

    async def test_optional_dates_and_manual_pagination(self):
        result, calls = await self.call({"news": []}, start="2026-10-01", end="2026-10-02T12:00:00Z", page_token="next", limit=0)
        self.assertTrue(result["available"])
        self.assertEqual(result["count"], 0)
        self.assertEqual(calls[0].url.params["page_token"], "next")
        self.assertEqual(calls[0].url.params["limit"], "1")
        self.assertNotIn("symbols", calls[0].url.params)

    async def test_failures_are_not_empty_success_or_retried(self):
        for status in (401, 403, 429, 500):
            with self.subTest(status=status):
                result, calls = await self.call({"message": "unavailable"}, status=status)
                self.assertFalse(result["available"])
                self.assertIn(str(status), result["error"])
                self.assertEqual(len(calls), 1)
                self.assertNotIn("news", result)

    async def test_invalid_queries_never_hit_network(self):
        for query in ({"start": "bad"}, {"start": "2026-10-02T12:00:00"}, {"start": "2026-10-03", "end": "2026-10-02"}, {"limit": "bad"}, {"symbols_csv": ",".join("S" + str(i) for i in range(31))}, {"page_token": "x" * 4097}):
            with self.subTest(query=str(query)[:50]):
                result, calls = await self.call({"news": []}, **query)
                self.assertFalse(result["available"])
                self.assertEqual(calls, [])

    async def test_bad_provider_schema_is_failure(self):
        for response in ({}, {"news": {}}, {"news": ["invalid"]}):
            result, _ = await self.call(response)
            self.assertFalse(result["available"])

    async def test_missing_credentials_never_hit_network(self):
        with patch.dict(os.environ, {"ALPACA_API_KEY": "", "ALPACA_API_SECRET": ""}), patch.object(httpx, "AsyncClient") as client:
            result = json.loads(await Tools().news())
            self.assertFalse(result["available"])
            client.assert_not_called()


if __name__ == "__main__":
    unittest.main()

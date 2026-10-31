"""Offline regressions: optional external market intelligence is read-only by default."""
import asyncio
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "openwebui/tools/market_data_gateway.py"
spec = importlib.util.spec_from_file_location("external_market_gateway", SRC)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FakeResponse:
    def __init__(self, status, payload=None):
        self.status_code = status
        self.payload = payload or {}

    def json(self):
        return self.payload


class FakeClient:
    calls = []
    response = FakeResponse(429)

    def __init__(self, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return self.response

    async def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self.response


class ExternalSourceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tool = module.Tools()
        FakeClient.calls = []

    async def test_gdelt_rejects_invalid_query_without_network(self):
        with patch.object(module.httpx, "AsyncClient", FakeClient):
            result = json.loads(await self.tool.catalyst_news_search("http://private.example"))
        self.assertEqual(result["error"], "invalid_query")
        self.assertFalse(FakeClient.calls)

    async def test_gdelt_rate_limit_is_explicit_no_retries(self):
        FakeClient.response = FakeResponse(429)
        with patch.object(module.httpx, "AsyncClient", FakeClient):
            result = json.loads(await self.tool.catalyst_news_search("semiconductors"))
        self.assertEqual(result["error"], "provider_rate_limited_429")
        self.assertEqual(len(FakeClient.calls), 1)
        self.assertEqual(result["orders_submitted"], 0)

    async def test_gdelt_preserves_source_metadata(self):
        FakeClient.response = FakeResponse(200, {"articles": [{
            "title": "Chip maker raises guidance",
            "url": "https://example.org/a",
            "domain": "example.org",
            "seendate": "20261026200000",
            "sourcecountry": "United States",
            "language": "English",
        }]})
        with patch.object(module.httpx, "AsyncClient", FakeClient):
            result = json.loads(await self.tool.catalyst_news_search("chip makers", top=1))
        self.assertTrue(result["ok"])
        self.assertEqual(result["article_count"], 1)
        self.assertEqual(result["articles"][0]["source_domain"], "example.org")
        self.assertEqual(len(FakeClient.calls), 1)

    async def test_barchart_refuses_unlicensed_calls(self):
        with patch.dict(module.os.environ, {"BARCHART_ALGO_USE_APPROVED": "0",
                                            "BARCHART_API_KEY": "not-used"}):
            with patch.object(module.httpx, "AsyncClient", FakeClient):
                result = json.loads(await self.tool.barchart_licensed_quotes("AAPL"))
        self.assertEqual(result["error"], "algorithmic_use_entitlement_not_confirmed")
        self.assertEqual(result["provider_calls"], 0)
        self.assertFalse(FakeClient.calls)

    async def test_barchart_no_key_no_request(self):
        with patch.dict(module.os.environ, {"BARCHART_ALGO_USE_APPROVED": "1",
                                            "BARCHART_API_KEY": ""}):
            with patch.object(module.httpx, "AsyncClient", FakeClient):
                result = json.loads(await self.tool.barchart_licensed_quotes("AAPL"))
        self.assertEqual(result["error"], "api_key_not_configured")
        self.assertFalse(FakeClient.calls)

    async def test_barchart_permitted_read_only_request(self):
        FakeClient.response = FakeResponse(200, {"status": {"code": 200},
            "results": [{"symbol": "AAPL", "mode": "I", "lastPrice": 195.0,
                         "volume": 500, "previousVolume": 400}]})
        with patch.dict(module.os.environ, {"BARCHART_ALGO_USE_APPROVED": "1",
                                            "BARCHART_API_KEY": "test-key"}):
            with patch.object(module.httpx, "AsyncClient", FakeClient):
                result = json.loads(await self.tool.barchart_licensed_quotes("AAPL"))
        self.assertTrue(result["ok"])
        self.assertEqual(result["quotes"][0]["symbol"], "AAPL")
        self.assertEqual(len(FakeClient.calls), 1)
        self.assertEqual(FakeClient.calls[0][0], "POST")
        self.assertEqual(result["orders_submitted"], 0)

    async def test_status_never_calls_external_provider(self):
        with patch.object(module.httpx, "AsyncClient", FakeClient):
            result = json.loads(await self.tool.external_source_status())
        self.assertEqual(result["provider_calls"], 0)
        self.assertFalse(FakeClient.calls)


if __name__ == "__main__":
    unittest.main()

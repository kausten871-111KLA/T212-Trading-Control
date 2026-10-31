"""Offline checks of approved Finviz and operator-owned import adapters."""
import asyncio
import importlib.util
import json
import os
import tempfile
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, main
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / "openwebui/tools/market_data_gateway.py"
spec = importlib.util.spec_from_file_location("market_gateway_licensed_imports", FILE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class MockResponse:
    def __init__(self, status=200, body=b"Ticker,Price\nAMD,195\n"):
        self.status_code = status
        self.content = body
        self.text = body.decode()
        self.headers = {"content-type": "text/csv"}


class MockClient:
    requests = []
    response = MockResponse()
    def __init__(self, **kwargs):
        pass
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        pass
    async def get(self, url, **kwargs):
        self.requests.append((url, kwargs))
        return self.response


class ReadOnlySourceTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tool = mod.Tools()
        MockClient.requests = []
        MockClient.response = MockResponse()

    async def test_finviz_no_entitlement_no_calls(self):
        with patch.dict(os.environ, {"FINVIZ_AUTOMATED_USE_APPROVED": "0",
                                      "FINVIZ_API_URL_SCREENER": "https://elite.finviz.com/api/"}, clear=False):
            with patch.object(mod.httpx, "AsyncClient", MockClient):
                result = json.loads(await self.tool.finviz_approved_api("screener"))
        self.assertEqual(result["error"], "account_api_entitlement_not_confirmed")
        self.assertFalse(MockClient.requests)

    async def test_finviz_disallows_other_hosts(self):
        with patch.dict(os.environ, {"FINVIZ_AUTOMATED_USE_APPROVED": "1",
                                      "FINVIZ_API_URL_SCREENER": "https://untrusted.example/api"}, clear=False):
            with patch.object(mod.httpx, "AsyncClient", MockClient):
                result = json.loads(await self.tool.finviz_approved_api())
        self.assertEqual(result["error"], "unapproved_api_host")
        self.assertFalse(MockClient.requests)

    async def test_finviz_csv_once_without_broker(self):
        with patch.dict(os.environ, {"FINVIZ_AUTOMATED_USE_APPROVED": "1",
                                      "FINVIZ_API_URL_SCREENER": "https://elite.finviz.com/api/example?token=SECRET"}, clear=False):
            with patch.object(mod.httpx, "AsyncClient", MockClient):
                result = json.loads(await self.tool.finviz_approved_api(top=2))
        self.assertTrue(result["ok"])
        self.assertEqual(result["records"][0]["Ticker"], "AMD")
        self.assertEqual(result["orders_submitted"], 0)
        self.assertEqual(len(MockClient.requests), 1)
        self.assertNotIn("SECRET", json.dumps(result))

    async def test_finviz_429_no_auto_retry(self):
        MockClient.response = MockResponse(status=429)
        with patch.dict(os.environ, {"FINVIZ_AUTOMATED_USE_APPROVED": "1",
                                      "FINVIZ_API_URL_SCREENER": "https://elite.finviz.com/api/example"}, clear=False):
            with patch.object(mod.httpx, "AsyncClient", MockClient):
                result = json.loads(await self.tool.finviz_approved_api())
        self.assertEqual(result["error"], "rate_limited_429")
        self.assertEqual(len(MockClient.requests), 1)

    async def test_import_requires_approval_and_no_data_reads(self):
        with patch.dict(os.environ, {"MARKET_IMPORT_APPROVED_SOURCES": ""}, clear=False):
            res = json.loads(await self.tool.approved_source_imports("t212_social"))
        self.assertEqual(res["error"], "automated_research_use_not_approved")
        self.assertEqual(res["file_reads"], 0)

    async def test_tradingview_separate_nondisplay_gate(self):
        with patch.dict(os.environ, {"MARKET_IMPORT_APPROVED_SOURCES": "tradingview",
                                      "TRADINGVIEW_NONDISPLAY_LICENSE_APPROVED": "0"}, clear=False):
            res = json.loads(await self.tool.approved_source_imports("tradingview"))
        self.assertEqual(res["error"], "tradingview_non_display_licence_required")

    async def test_no_arbitrary_filename(self):
        with patch.dict(os.environ, {"MARKET_IMPORT_APPROVED_SOURCES": "reddit"}, clear=False):
            res = json.loads(await self.tool.approved_source_imports("../reddit"))
        self.assertEqual(res["error"], "unknown_source")

    async def test_import_absent_is_not_misrepresented_as_live(self):
        with patch.dict(os.environ, {"MARKET_IMPORT_APPROVED_SOURCES": "stocktwits"}, clear=False):
            res = json.loads(await self.tool.approved_source_imports("stocktwits"))
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"], "approved_import_file_not_installed")


if __name__ == "__main__":
    main()

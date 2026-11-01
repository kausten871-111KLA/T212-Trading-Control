"""Read-only Alpaca news catalyst method tests. No real network or broker requests."""
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / "openwebui/tools/market_data_gateway.py"
spec = importlib.util.spec_from_file_location("alpaca_market_gateway_news", FILE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class NewsCatalystTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tool = module.Tools()

    async def test_news_uses_bounded_existing_alpaca_api(self):
        provider = {"news": [{
            "headline": "Example catalyst",
            "summary": "Test press-release summary",
            "url": "https://example.org/story",
            "source": "test-feed",
            "created_at": "2026-10-26T19:00:00Z",
            "symbols": ["AMD"],
        }]}
        with patch.object(self.tool, "_get", new_callable=AsyncMock, return_value=(provider, None)) as get:
            result = json.loads(await self.tool.alpaca_news_catalysts("amd", 24, 5))
        self.assertTrue(result["ok"])
        self.assertEqual(result["orders_submitted"], 0)
        self.assertEqual(result["articles"][0]["symbols"], ["AMD"])
        self.assertTrue(result["articles"][0]["unverified_catalyst_lead"])
        args, kwargs = get.await_args
        self.assertEqual(args, (self.tool.data_base, "/v1beta1/news"))
        self.assertEqual(kwargs["params"]["symbols"], "AMD")
        self.assertEqual(kwargs["params"]["limit"], 5)
        self.assertEqual(kwargs["params"]["include_content"], "false")

    async def test_invalid_symbols_never_call_provider(self):
        with patch.object(self.tool, "_get", new_callable=AsyncMock) as get:
            result = json.loads(await self.tool.alpaca_news_catalysts("../../etc/passwd"))
        self.assertEqual(result["error"], "invalid_symbols")
        get.assert_not_awaited()

    async def test_invalid_parameters_never_call_provider(self):
        with patch.object(self.tool, "_get", new_callable=AsyncMock) as get:
            result = json.loads(await self.tool.alpaca_news_catalysts("", "NaN", 10))
        self.assertEqual(result["error"], "invalid_parameters")
        get.assert_not_awaited()

    async def test_provider_403_does_not_claim_available(self):
        with patch.object(self.tool, "_get", new_callable=AsyncMock, return_value=(None, "Alpaca data API error 403")):
            result = json.loads(await self.tool.alpaca_news_catalysts("AAPL"))
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "provider_error")
        self.assertEqual(result["orders_submitted"], 0)

    async def test_empty_news_is_valid(self):
        with patch.object(self.tool, "_get", new_callable=AsyncMock, return_value=({"news": []}, None)):
            result = json.loads(await self.tool.alpaca_news_catalysts(top=2))
        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 0)


if __name__ == "__main__":
    unittest.main()

"""Offline coverage of Twelve Data's authenticated bridge and WebUI tool."""
from __future__ import annotations
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch, AsyncMock, MagicMock

from runtime.deepseek.host_command_bridge import execute,COMMANDS

HERE=Path(__file__).resolve().parent.parent/"openwebui/tools"
sys.path.insert(0,str(HERE))
from twelve_data_webui_tool import Tools as TwelveTool


class TwelveDataBridgeTests(unittest.TestCase):
    def test_allowed_operations_are_research_only(self):
        for command in ("twelve_data_quote","twelve_data_series",
                        "twelve_data_search","twelve_data_usage"):
            self.assertIn(command,COMMANDS)

    def test_host_routes_valid_market_request(self):
        with patch("runtime.deepseek.twelve_data_adapter.query",
                   return_value={"ok":True,"endpoint":"quote","symbol":"TSCO"}) as mock:
            value=execute("twelve_data_quote",symbol="TSCO",
                          exchange="LSE",mic_code="XLON",
                          interval="1day",outputsize=30)
        self.assertTrue(value["ok"])
        mock.assert_called_once_with("quote",symbol="TSCO",exchange="LSE",
                       mic_code="XLON",interval="1day",outputsize=30)

    def test_host_denies_arbitrary_operation(self):
        response=execute("sudo rm -rf /")
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"],"unknown_command")

    def test_api_usage_calls_usage_only(self):
        with patch("runtime.deepseek.twelve_data_adapter.query",
                   return_value={"ok":True,"endpoint":"api_usage"}) as mock:
            response=execute("twelve_data_usage",symbol="AAPL")
        self.assertTrue(response["ok"])
        self.assertEqual(mock.call_args.args[0],"api_usage")

    def test_no_orders_imported_in_adapter(self):
        source=(Path(__file__).resolve().parent.parent/"runtime/deepseek/twelve_data_adapter.py").read_text()
        for forbidden in ("trading212_demo_gateway","place_market_order","subprocess.run","execute_trade"):
            self.assertNotIn(forbidden,source)


class TwelveDataWebUITests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_makes_named_bridge_request_without_exposing_token(self):
        capture={}
        class Client:
            def __init__(self,**kwargs):
                self.kwargs=kwargs
            async def __aenter__(self):return self
            async def __aexit__(self,*args):return False
            async def post(self,url,*,json,headers):
                capture.update({"url":url,"payload":json,
                                "token_set":bool(headers.get("X-Bridge-Token"))})
                return SimpleNamespace(status_code=200,json=lambda:{
                    "ok":True,"provider":"Twelve Data","symbol":"TSCO",
                    "exchange":"LSE","currency":"GBX","execution_quote":False
                })
        with patch("twelve_data_webui_tool.Path.read_text",
                   return_value="x"*64),patch("twelve_data_webui_tool.httpx.AsyncClient",Client):
            reply=await TwelveTool().twelve_data_research(
                operation="quote",symbol="TSCO",exchange="LSE")
        result=json.loads(reply)
        self.assertTrue(result["ok"])
        self.assertEqual(capture["payload"]["command"],"twelve_data_quote")
        self.assertEqual(capture["payload"]["exchange"],"LSE")
        self.assertEqual(result["currency"],"GBX")
        self.assertTrue(capture["token_set"])
        self.assertNotIn("x"*64,reply)

    async def test_invalid_outputsize_not_sent(self):
        res=await TwelveTool().twelve_data_research(
            operation="time_series",symbol="TSCO",outputsize=101)
        self.assertEqual(json.loads(res)["error"],"invalid_data_request")

    async def test_bridge_failure_redacted(self):
        class Failure:
            def __init__(self,**kwargs):pass
            async def __aenter__(self):return self
            async def __aexit__(self,*args):return False
            async def post(self,*args,**kwargs):
                raise RuntimeError("debug contains secret")
        with patch("twelve_data_webui_tool.Path.read_text",
                   return_value="x"*64),patch("twelve_data_webui_tool.httpx.AsyncClient",Failure):
            res=await TwelveTool().twelve_data_research(operation="quote")
        data=json.loads(res)
        self.assertFalse(data["ok"])
        self.assertNotIn("secret",res)

if __name__=="__main__":
    unittest.main()

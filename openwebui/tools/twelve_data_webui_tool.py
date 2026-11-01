"""
title: Twelve Data Global Market Research
author: Trading Operations Engineering
description: Authenticated, quota-tracked global equity data via the existing Contabo bridge. No second broker, trade execution or key exposure.
version: 0.1.0
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Literal
import httpx
from pydantic import BaseModel


class Tools:
    class Valves(BaseModel):
        pass

    def __init__(self):
        self.valves = self.Valves()

    async def twelve_data_research(
        self,
        operation: Literal["quote","time_series","symbol_search","api_usage"] = "quote",
        symbol: str = "AAPL",
        exchange: str = "",
        mic_code: str = "",
        interval: Literal["1min","5min","15min","30min","1h","1day","1week"] = "1day",
        outputsize: int = 30,
    ) -> str:
        """Query Twelve Data for global market research via the same Contabo worker.

        :param operation: quote for recent quote; time_series for dated OHLCV bars; symbol_search to check ticker/exchange; api_usage to inspect credits. Do not request expensive market-movers or cross endpoints.
        :param symbol: Stock ticker or exact symbol search term, e.g. AAPL, TSCO, ASML.
        :param exchange: Explicit exchange filter when needed (e.g. LSE, XETRA, NASDAQ). Always verify returned MIC/currency before T212 instrument matching.
        :param mic_code: Optional market identifier code (e.g. XLON, XNAS).
        :param interval: Interval for time_series; 1day by default. Intraday UTC requested; daily bars preserve exchange-local date.
        :param outputsize: Number of OHLCV bars 1..100, default 30. This controls response size, not a trade limit.
        """
        mapping={
            "quote":"twelve_data_quote",
            "time_series":"twelve_data_series",
            "symbol_search":"twelve_data_search",
            "api_usage":"twelve_data_usage",
        }
        if operation not in mapping or isinstance(outputsize,bool) or not 1 <= outputsize <= 100:
            return json.dumps({"ok":False,"error":"invalid_data_request"})
        path="/run/contabo-bridge/command.sock"
        try:
            token=Path("/run/contabo-bridge/bridge.token").read_text(encoding="utf-8").strip()
            if len(token)<48:
                return json.dumps({"ok":False,"error":"bridge_token_not_configured"})
            async with httpx.AsyncClient(
                timeout=25,trust_env=False,transport=httpx.AsyncHTTPTransport(uds=path)
            ) as client:
                response=await client.post(
                    "http://localhost/command",
                    json={"command":mapping[operation],"symbol":symbol,
                          "exchange":exchange,"mic_code":mic_code,
                          "interval":interval,"outputsize":outputsize},
                    headers={"X-Bridge-Token":token,"Accept":"application/json"},
                )
            if response.status_code!=200:
                return json.dumps({"ok":False,"error":"bridge_http_error",
                                   "http_status":response.status_code})
            # The host adapter already omits provider keys and limits result size.
            parsed=response.json()
            if not isinstance(parsed,dict):
                return json.dumps({"ok":False,"error":"invalid_bridge_response"})
            result=json.dumps(parsed,ensure_ascii=False,separators=(",",":"))
            if len(result)>28000:
                return json.dumps({"ok":False,"error":"data_result_too_large"})
            return result
        except Exception as error:
            return json.dumps({"ok":False,"error":"bridge_request_error",
                               "error_type":type(error).__name__})

"""
title: Market Data Gateway
author: Katie / OpenAI
description: Read-only US-equity market-data toolkit for DeepSeek/Open WebUI. Alpaca data only; never submits trades. Designed to feed T212 DEMO Scout/Investigator/Decision workflows.
version: 0.1.0
"""

import os
import json
import math
from typing import List
import httpx


class Tools:
    def __init__(self):
        self.data_base = "https://data.alpaca.markets"
        self.trading_base = "https://paper-api.alpaca.markets"

    def _credentials(self):
        return (
            os.getenv("ALPACA_API_KEY", "").strip(),
            os.getenv("ALPACA_API_SECRET", "").strip(),
        )

    def _headers(self):
        key, secret = self._credentials()
        if not key or not secret:
            return None
        return {
            "APCA-API-KEY-ID": key,
            "APCA-API-SECRET-KEY": secret,
            "Accept": "application/json",
        }

    def _show(self, value):
        if isinstance(value, str):
            return value
        return json.dumps(value, indent=2, default=str)

    async def _get(self, base, path, params=None):
        headers = self._headers()
        if not headers:
            return None, (
                "Alpaca market-data credentials are not available to Open WebUI. "
                "Set ALPACA_API_KEY and ALPACA_API_SECRET server-side. "
                "Do not paste keys into chat."
            )

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{base}{path}",
                    params=params or {},
                    headers=headers,
                )
                try:
                    data = response.json()
                except Exception:
                    data = response.text

                if response.is_error:
                    return None, f"Alpaca data API error {response.status_code}: {data}"

                return data, None
        except Exception as exc:
            return None, f"Alpaca data connection error: {type(exc).__name__}: {exc}"

    def _symbols(self, symbols_csv: str, max_symbols: int = 30) -> List[str]:
        raw = [x.strip().upper() for x in (symbols_csv or "").replace("\n", ",").split(",")]
        seen = set()
        symbols = []
        for symbol in raw:
            if symbol and symbol not in seen:
                seen.add(symbol)
                symbols.append(symbol)
            if len(symbols) >= max_symbols:
                break
        return symbols

    def _spread_metrics(self, quote):
        if not isinstance(quote, dict):
            return {}
        bid = quote.get("bp")
        ask = quote.get("ap")
        try:
            bid = float(bid)
            ask = float(ask)
            if bid <= 0 or ask <= 0 or ask < bid:
                return {}
            mid = (bid + ask) / 2.0
            spread = ask - bid
            return {
                "bid": bid,
                "ask": ask,
                "spread": spread,
                "spreadPct": (spread / mid * 100.0) if mid else None,
            }
        except Exception:
            return {}

    def _snapshot_summary(self, symbol, snap):
        if not isinstance(snap, dict):
            return {"symbol": symbol, "raw": snap}

        latest_quote = snap.get("latestQuote") or snap.get("latest_quote") or {}
        latest_trade = snap.get("latestTrade") or snap.get("latest_trade") or {}
        minute_bar = snap.get("minuteBar") or snap.get("minute_bar") or {}
        daily_bar = snap.get("dailyBar") or snap.get("daily_bar") or {}
        prev_bar = snap.get("prevDailyBar") or snap.get("previousDailyBar") or snap.get("previous_daily_bar") or {}

        price = (
            latest_trade.get("p")
            or minute_bar.get("c")
            or daily_bar.get("c")
        )
        prev_close = prev_bar.get("c")
        change_pct = None
        try:
            if price is not None and prev_close not in (None, 0):
                change_pct = (float(price) / float(prev_close) - 1.0) * 100.0
        except Exception:
            pass

        result = {
            "symbol": symbol,
            "price": price,
            "changePctVsPrevClose": change_pct,
            "minuteVolume": minute_bar.get("v"),
            "dayVolume": daily_bar.get("v"),
            "dayOpen": daily_bar.get("o"),
            "dayHigh": daily_bar.get("h"),
            "dayLow": daily_bar.get("l"),
            "previousClose": prev_close,
            "quoteTimestamp": latest_quote.get("t"),
            "tradeTimestamp": latest_trade.get("t"),
        }
        result.update(self._spread_metrics(latest_quote))
        return result

    async def market_clock(self) -> str:
        """
        Return the current US market clock from Alpaca Paper API.
        Read-only. Does not inspect or change an Alpaca trading account.
        """
        data, error = await self._get(self.trading_base, "/v2/clock")
        return error or self._show(data)

    async def top_movers(self, top: int = 20) -> str:
        """
        Return current top US stock gainers and losers from Alpaca's screener endpoint.
        Read-only. Some Alpaca plans may restrict this endpoint; exact 403/plan errors are returned.
        :param top: Number of gainers and losers requested, 1-50.
        """
        top = max(1, min(int(top), 50))
        data, error = await self._get(
            self.data_base,
            "/v1beta1/screener/stocks/movers",
            params={"top": top},
        )
        return error or self._show(data)

    async def most_active(self, top: int = 30, by: str = "volume") -> str:
        """
        Return the most active US stocks by volume or trade count.
        Read-only. Some Alpaca plans may restrict this endpoint.
        :param top: Number of symbols, 1-100.
        :param by: volume or trades.
        """
        top = max(1, min(int(top), 100))
        by = (by or "volume").strip().lower()
        if by not in ("volume", "trades"):
            return "by must be 'volume' or 'trades'."

        data, error = await self._get(
            self.data_base,
            "/v1beta1/screener/stocks/most-actives",
            params={"top": top, "by": by},
        )
        return error or self._show(data)

    async def latest_quotes(self, symbols_csv: str, feed: str = "iex") -> str:
        """
        Return latest bid/ask quotes for up to 30 US stock symbols.
        Use IEX by default on free/basic Alpaca market data.
        :param symbols_csv: Comma-separated symbols, e.g. AAPL,NVDA,AMD.
        :param feed: iex, delayed_sip, sip, boats, overnight or otc.
        """
        symbols = self._symbols(symbols_csv)
        if not symbols:
            return "No symbols supplied."

        allowed = {"iex", "delayed_sip", "sip", "boats", "overnight", "otc"}
        feed = (feed or "iex").strip().lower()
        if feed not in allowed:
            return f"Unsupported feed '{feed}'."

        data, error = await self._get(
            self.data_base,
            "/v2/stocks/quotes/latest",
            params={"symbols": ",".join(symbols), "feed": feed},
        )
        return error or self._show(data)

    async def snapshots(self, symbols_csv: str, feed: str = "iex") -> str:
        """
        Return latest quote/trade/minute/day/previous-day snapshots for up to 30 symbols.
        Produces a compact summary suitable for qualification gates.
        :param symbols_csv: Comma-separated symbols.
        :param feed: iex by default; use only feeds permitted by the Alpaca plan.
        """
        symbols = self._symbols(symbols_csv)
        if not symbols:
            return "No symbols supplied."

        feed = (feed or "iex").strip().lower()
        allowed = {"iex", "delayed_sip", "sip", "boats", "overnight", "otc"}
        if feed not in allowed:
            return f"Unsupported feed '{feed}'."

        data, error = await self._get(
            self.data_base,
            "/v2/stocks/snapshots",
            params={"symbols": ",".join(symbols), "feed": feed},
        )
        if error:
            return error

        snapshots = data.get("snapshots", data) if isinstance(data, dict) else {}
        rows = []
        for symbol in symbols:
            snap = snapshots.get(symbol, {}) if isinstance(snapshots, dict) else {}
            rows.append(self._snapshot_summary(symbol, snap))

        return self._show(
            {
                "provider": "Alpaca",
                "feed": feed,
                "readOnly": True,
                "symbols": rows,
            }
        )

    async def bars(
        self,
        symbols_csv: str,
        timeframe: str = "1Min",
        start: str = "",
        end: str = "",
        limit: int = 1000,
        feed: str = "iex",
    ) -> str:
        """
        Return historical bars for up to 30 symbols.
        Prefer explicit ISO-8601 start/end timestamps for intraday analysis.
        :param symbols_csv: Comma-separated symbols.
        :param timeframe: e.g. 1Min, 5Min, 15Min, 1Hour, 1Day.
        :param start: ISO-8601 start timestamp.
        :param end: ISO-8601 end timestamp.
        :param limit: 1-10000.
        :param feed: iex by default.
        """
        symbols = self._symbols(symbols_csv)
        if not symbols:
            return "No symbols supplied."

        params = {
            "symbols": ",".join(symbols),
            "timeframe": timeframe,
            "limit": max(1, min(int(limit), 10000)),
            "feed": (feed or "iex").strip().lower(),
            "sort": "asc",
        }
        if start:
            params["start"] = start
        if end:
            params["end"] = end

        data, error = await self._get(
            self.data_base,
            "/v2/stocks/bars",
            params=params,
        )
        return error or self._show(data)

    async def candidate_scan(self, top: int = 20, feed: str = "iex") -> str:
        """
        Build a compact Scout candidate set by combining movers and most-actives, then adding snapshots.
        Read-only. Never places an order.
        If Alpaca plan restrictions block a screener endpoint, returns the exact blocker.
        """
        top = max(5, min(int(top), 30))

        movers, mover_error = await self._get(
            self.data_base,
            "/v1beta1/screener/stocks/movers",
            params={"top": top},
        )
        actives, active_error = await self._get(
            self.data_base,
            "/v1beta1/screener/stocks/most-actives",
            params={"top": top, "by": "volume"},
        )

        symbols = []
        seen = set()

        if isinstance(movers, dict):
            for key in ("gainers", "losers"):
                for item in movers.get(key, []) or []:
                    symbol = str(item.get("symbol", "")).upper()
                    if symbol and symbol not in seen:
                        seen.add(symbol)
                        symbols.append(symbol)

        if isinstance(actives, dict):
            active_rows = (
                actives.get("most_actives")
                or actives.get("mostActives")
                or actives.get("stocks")
                or []
            )
            for item in active_rows:
                symbol = str(item.get("symbol", "")).upper()
                if symbol and symbol not in seen:
                    seen.add(symbol)
                    symbols.append(symbol)

        symbols = symbols[:30]

        snapshot_rows = []
        snapshot_error = None
        if symbols:
            data, snapshot_error = await self._get(
                self.data_base,
                "/v2/stocks/snapshots",
                params={"symbols": ",".join(symbols), "feed": (feed or "iex").strip().lower()},
            )
            if isinstance(data, dict):
                snaps = data.get("snapshots", data)
                for symbol in symbols:
                    snapshot_rows.append(
                        self._snapshot_summary(
                            symbol,
                            snaps.get(symbol, {}) if isinstance(snaps, dict) else {},
                        )
                    )

        return self._show(
            {
                "provider": "Alpaca",
                "readOnly": True,
                "feed": feed,
                "moversError": mover_error,
                "mostActiveError": active_error,
                "snapshotError": snapshot_error,
                "candidateCount": len(snapshot_rows),
                "candidates": snapshot_rows,
                "note": (
                    "This is a discovery/qualification feed only. "
                    "T212 DEMO remains the sole execution gateway."
                ),
            }
        )

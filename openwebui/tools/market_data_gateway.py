"""
title: Market Data Gateway
author: Katie / OpenAI
description: Read-only US-equity market-data toolkit for DeepSeek/Open WebUI. Alpaca data only; never submits trades. Designed to feed T212 DEMO Scout/Investigator/Decision workflows.
version: 0.2.0
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
            "previousVolume": prev_bar.get("v"),
            "quoteTimestamp": latest_quote.get("t"),
            "tradeTimestamp": latest_trade.get("t"),
        }
        result.update(self._spread_metrics(latest_quote))
        return result

    async def health_check(self, test_screeners: bool = True) -> str:
        """
        Read-only market-data preflight. Confirms credentials are loaded and tests the market clock.
        Optionally probes Alpaca screener access so plan restrictions are surfaced explicitly.
        Never places or modifies an order.
        :param test_screeners: When true, probe movers and most-active endpoints.
        """
        headers = self._headers()
        if not headers:
            return self._show(
                {
                    "provider": "Alpaca",
                    "readOnly": True,
                    "credentialsLoaded": False,
                    "ready": False,
                    "error": (
                        "ALPACA_API_KEY / ALPACA_API_SECRET are not available "
                        "to the Open WebUI server."
                    ),
                }
            )

        clock, clock_error = await self._get(self.trading_base, "/v2/clock")

        movers_error = None
        actives_error = None
        if test_screeners:
            _, movers_error = await self._get(
                self.data_base,
                "/v1beta1/screener/stocks/movers",
                params={"top": 1},
            )
            _, actives_error = await self._get(
                self.data_base,
                "/v1beta1/screener/stocks/most-actives",
                params={"top": 1, "by": "volume"},
            )

        return self._show(
            {
                "provider": "Alpaca",
                "readOnly": True,
                "credentialsLoaded": True,
                "clockAvailable": clock_error is None,
                "clockError": clock_error,
                "clock": clock,
                "screenerProbeRequested": bool(test_screeners),
                "moversAvailable": None if not test_screeners else movers_error is None,
                "moversError": movers_error,
                "mostActiveAvailable": None if not test_screeners else actives_error is None,
                "mostActiveError": actives_error,
                "readyForQuotesSnapshotsBars": clock_error is None,
                "note": (
                    "Screener 403/plan restrictions do not prevent quote/snapshot use. "
                    "Use scan_symbols with iex or delayed_sip when a candidate universe is supplied."
                ),
            }
        )

    async def asset_universe(
        self,
        exchange: str = "",
        limit: int = 500,
    ) -> str:
        """
        Return a bounded list of active US-equity assets from Alpaca.
        Read-only. Useful for building a candidate universe; does not imply T212 tradability.
        :param exchange: Optional exchange filter such as NASDAQ, NYSE, AMEX, ARCA.
        :param limit: Maximum assets returned, 1-1000.
        """
        limit = max(1, min(int(limit), 1000))
        params = {"status": "active", "asset_class": "us_equity"}
        exchange = (exchange or "").strip().upper()
        if exchange:
            params["exchange"] = exchange

        data, error = await self._get(self.trading_base, "/v2/assets", params=params)
        if error:
            return error

        rows = []
        for item in data if isinstance(data, list) else []:
            if len(rows) >= limit:
                break
            rows.append(
                {
                    "symbol": item.get("symbol"),
                    "name": item.get("name"),
                    "exchange": item.get("exchange"),
                    "status": item.get("status"),
                    "tradable": item.get("tradable"),
                    "fractionable": item.get("fractionable"),
                }
            )

        return self._show(
            {
                "provider": "Alpaca",
                "readOnly": True,
                "count": len(rows),
                "assets": rows,
                "note": "Alpaca asset availability is not proof the instrument exists in T212.",
            }
        )

    async def scan_symbols(
        self,
        symbols_csv: str,
        top: int = 20,
        feed: str = "delayed_sip",
    ) -> str:
        """
        Rank a supplied US-equity symbol universe by percentage change versus previous close.
        This provides a free/basic-plan-friendly fallback when real-time SIP screener endpoints
        are unavailable. Read-only; never places orders.
        :param symbols_csv: Comma-separated symbols, up to 30 per call.
        :param top: Number of gainers and losers to return, 1-30.
        :param feed: delayed_sip by default for consolidated delayed coverage; iex for free real-time IEX.
        """
        symbols = self._symbols(symbols_csv, max_symbols=30)
        if not symbols:
            return "No symbols supplied."

        top = max(1, min(int(top), 30))
        feed = (feed or "delayed_sip").strip().lower()
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
            row = self._snapshot_summary(symbol, snap)
            if row.get("price") is not None:
                rows.append(row)

        ranked = [
            row for row in rows
            if isinstance(row.get("changePctVsPrevClose"), (int, float))
            and math.isfinite(row.get("changePctVsPrevClose"))
        ]
        ranked.sort(key=lambda row: row.get("changePctVsPrevClose"), reverse=True)

        return self._show(
            {
                "provider": "Alpaca",
                "feed": feed,
                "readOnly": True,
                "universeCount": len(symbols),
                "pricedCount": len(rows),
                "topGainers": ranked[:top],
                "topLosers": list(reversed(ranked[-top:])),
                "note": (
                    "Ranks only the supplied symbol universe. "
                    "Use exact timestamps/feed labels when making trading decisions."
                ),
            }
        )

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

    async def market_insights_discovery(
        self, top: int = 20, feed: str = "iex", max_age_seconds: int = 300
    ) -> str:
        """Discover current US gainers and activity from the existing Alpaca entitlement.

        Provides an evidence-labelled alternative to manually viewed TradingView,
        StockAnalysis and Yahoo Finance pages. It does NOT scrape those sites,
        access broker orders or claim consolidated quotes from IEX.
        :param top: Number of screener seeds (5-30).
        :param feed: Existing Alpaca IEX or delayed SIP feed entitlement.
        :param max_age_seconds: Maximum observed quote/trade age (30-1800 seconds).
        """
        from datetime import datetime, timezone

        feed = str(feed or "").strip().lower()
        if feed not in {"iex", "delayed_sip"}:
            return self._show({"ok": False, "error": "unsupported_feed"})
        try:
            top = max(5, min(int(top), 30))
            age_limit = max(30, min(int(max_age_seconds), 1800))
        except (TypeError, ValueError, OverflowError):
            return self._show({"ok": False, "error": "invalid_parameters"})

        try:
            raw = await self.candidate_scan(top=top, feed=feed)
            scan = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError, json.JSONDecodeError):
            return self._show({"ok": False, "error": "candidate_scan_invalid_response"})
        if not isinstance(scan, dict) or not isinstance(scan.get("candidates"), list):
            return self._show({"ok": False, "error": "candidate_scan_unavailable"})

        now = datetime.now(timezone.utc)
        rows = []
        rejected = {"missing_or_invalid_timestamp": 0, "stale_or_future": 0}
        for row in scan["candidates"]:
            if not isinstance(row, dict):
                continue
            observations = []
            for key in ("quoteTimestamp", "tradeTimestamp"):
                value = row.get(key)
                if not isinstance(value, str) or not value.strip():
                    continue
                try:
                    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    if parsed.tzinfo is not None and parsed.utcoffset() is not None:
                        observations.append(parsed.astimezone(timezone.utc))
                except (ValueError, OverflowError):
                    continue
            if not observations:
                rejected["missing_or_invalid_timestamp"] += 1
                continue
            latest = max(observations)
            age = (now - latest).total_seconds()
            if age < -30 or age > age_limit:
                rejected["stale_or_future"] += 1
                continue
            # Provider payloads can contain non-finite numbers; never pass
            # NaN/Infinity through to model-facing JSON or winner ranking.
            try:
                change = float(row["changePctVsPrevClose"])
                if not math.isfinite(change):
                    change = None
            except (TypeError, ValueError, KeyError, OverflowError):
                change = None
            try:
                price = float(row["price"])
                if not math.isfinite(price) or price <= 0:
                    price = None
            except (TypeError, ValueError, KeyError, OverflowError):
                price = None
            day_volume = None
            previous_session_volume_ratio = None
            try:
                volume = float(row["dayVolume"])
                previous = float(row["previousVolume"])
                if math.isfinite(volume) and volume >= 0:
                    day_volume = volume
                    if math.isfinite(previous) and previous > 0:
                        previous_session_volume_ratio = round(volume / previous, 3)
            except (TypeError, ValueError, KeyError, OverflowError, ZeroDivisionError):
                pass
            rows.append({
                "symbol": row.get("symbol"),
                "price": price,
                "change_pct_vs_previous_close": change,
                "day_volume": day_volume,
                "previous_session_volume_ratio": previous_session_volume_ratio,
                "volume_ratio_is_rvol": False,
                "bid": row.get("bid"),
                "ask": row.get("ask"),
                "spread_pct": row.get("spreadPct"),
                "quote_venue": feed,
                "observation_at_utc": latest.isoformat(),
                "observation_age_seconds": round(max(0.0, age), 3),
                "source": "alpaca:candidate_scan",
                "broker_tradability_verified": False,
            })
        rows.sort(
            key=lambda item: (
                item["change_pct_vs_previous_close"] is not None,
                item["change_pct_vs_previous_close"]
                if item["change_pct_vs_previous_close"] is not None else -999999.0,
            ),
            reverse=True,
        )
        return self._show({
            "ok": bool(rows),
            "provider": "Alpaca",
            "source": "alpaca:candidate_scan",
            "feed": feed,
            "observed_at_utc": now.isoformat(),
            "market": "US equities",
            "read_only_market_research": True,
            "orders_submitted_by_tool": 0,
            "entitlement": "requires_existing_provider_permission",
            "not_tradingview_stockanalysis_or_yahoo_data": True,
            "screener_may_include_previous_session_seeds": True,
            "requires_broker_quote_and_instrument_verification": True,
            "movers_error": scan.get("moversError"),
            "most_active_error": scan.get("mostActiveError"),
            "snapshot_error": scan.get("snapshotError"),
            "candidate_count": len(rows),
            "rejected": rejected,
            "candidates": rows,
        })


    async def catalyst_news_search(
        self, query: str, hours: int = 24, top: int = 15
    ) -> str:
        """
        Query the documented GDELT DOC 2.0 news-index API for catalyst research.
        This is NOT Yahoo/TradingView/Investing.com content; it returns article links
        and metadata only, with no assertion of financial data rights or freshness.
        One bounded request, no retry and no broker operations.
        :param query: Company, ticker, sector or catalyst keyword, 2-120 characters.
        :param hours: News discovery lookback, 1-72 hours.
        :param top: Maximum articles returned, 1-25.
        """
        from datetime import datetime, timezone
        import re

        query = str(query or "").strip()
        if not 2 <= len(query) <= 120 or not re.fullmatch(
            r"[A-Za-z0-9\s.,+&()'/-]+", query
        ):
            return self._show({"ok": False, "source": "GDELT DOC 2.0",
                               "error": "invalid_query", "orders_submitted": 0})
        try:
            hours = max(1, min(72, int(hours)))
            top = max(1, min(25, int(top)))
        except (ValueError, TypeError, OverflowError):
            return self._show({"ok": False, "source": "GDELT DOC 2.0",
                               "error": "invalid_parameters", "orders_submitted": 0})
        params = {"query": query, "mode": "artlist", "format": "json",
                  "maxrecords": top, "timespan": f"{hours}h"}
        try:
            async with httpx.AsyncClient(timeout=12.0, follow_redirects=False) as client:
                response = await client.get(
                    "https://api.gdeltproject.org/api/v2/doc/doc",
                    params=params, headers={"Accept": "application/json"},
                )
            if response.status_code == 429:
                return self._show({"ok": False, "source": "GDELT DOC 2.0",
                                   "error": "provider_rate_limited_429",
                                   "orders_submitted": 0})
            if response.status_code != 200:
                return self._show({"ok": False, "source": "GDELT DOC 2.0",
                                   "error": "provider_http_" + str(response.status_code),
                                   "orders_submitted": 0})
            payload = response.json()
            articles = payload.get("articles", []) if isinstance(payload, dict) else []
            rows = [
                {
                    "title": str(row.get("title", ""))[:240],
                    "url": str(row.get("url", ""))[:600],
                    "source_domain": str(row.get("domain", ""))[:120],
                    "source_country": str(row.get("sourcecountry", ""))[:40],
                    "seendate": str(row.get("seendate", ""))[:40],
                    "language": str(row.get("language", ""))[:25],
                    "unverified_news_catalyst": True,
                }
                for row in articles[:top]
                if isinstance(row, dict)
                and str(row.get("url", "")).startswith(("https://", "http://"))
            ]
            return self._show({
                "ok": True, "provider": "GDELT DOC 2.0",
                "read_only": True, "orders_submitted": 0,
                "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
                "lookback_hours": hours, "query": query, "article_count": len(rows),
                "articles": rows,
                "note": "News-index leads only. Verify original reporting, ticker, "
                        "publication time and market impact before any trade decision.",
            })
        except (httpx.RequestError, ValueError, TypeError) as exc:
            return self._show({
                "ok": False, "source": "GDELT DOC 2.0",
                "error": "provider_unavailable_or_invalid_response",
                "error_type": type(exc).__name__, "orders_submitted": 0,
            })

    async def barchart_licensed_quotes(self, symbols_csv: str) -> str:
        """
        Quote lookup using Barchart OnDemand ONLY if an already-owned entitlement
        explicitly authorises automated/algorithmic use. Never buys a subscription.
        :param symbols_csv: Up to 10 US share symbols, comma-separated.
        """
        import re
        symbols = [
            symbol for symbol in self._symbols(symbols_csv, max_symbols=10)
            if re.fullmatch(r"[A-Z0-9.^-]{1,15}", symbol)
        ]
        if not symbols:
            return self._show({"ok": False, "source": "Barchart OnDemand",
                               "error": "no_valid_symbols", "orders_submitted": 0})
        if os.getenv("BARCHART_ALGO_USE_APPROVED", "").strip() != "1":
            return self._show({"ok": False, "source": "Barchart OnDemand",
                               "error": "algorithmic_use_entitlement_not_confirmed",
                               "orders_submitted": 0, "provider_calls": 0})
        key = os.getenv("BARCHART_API_KEY", "").strip()
        if not key:
            return self._show({"ok": False, "source": "Barchart OnDemand",
                               "error": "api_key_not_configured",
                               "orders_submitted": 0, "provider_calls": 0})
        try:
            # Provider documents POST form-data to keep key out of URL parameters.
            async with httpx.AsyncClient(timeout=12.0, follow_redirects=False) as client:
                response = await client.post(
                    "https://ondemand.websol.barchart.com/getQuote.json",
                    data={"apikey": key, "symbols": ",".join(symbols)},
                    headers={"Accept": "application/json"},
                )
            if response.status_code != 200:
                return self._show({"ok": False, "source": "Barchart OnDemand",
                                   "error": "provider_http_" + str(response.status_code),
                                   "orders_submitted": 0})
            data = response.json()
            if not isinstance(data, dict) or data.get("status", {}).get("code") != 200:
                return self._show({"ok": False, "source": "Barchart OnDemand",
                                   "error": "provider_status_not_success",
                                   "orders_submitted": 0})
            fields = ("symbol", "name", "mode", "lastPrice", "tradeTimestamp",
                      "preMarketPrice", "preMarketTimestamp", "percentChange",
                      "volume", "previousVolume", "serverTimestamp")
            quotes = [
                {field: row.get(field) for field in fields}
                for row in data.get("results", [])[:10] if isinstance(row, dict)
            ]
            return self._show({"ok": True, "source": "Barchart OnDemand",
                               "read_only": True, "orders_submitted": 0,
                               "quotes": quotes,
                               "broker_tradability_verified": False,
                               "note": "Quote mode R/I/D depends on licence. "
                                       "Verify venue, timestamps and T212 prices."})
        except (httpx.RequestError, ValueError, TypeError) as exc:
            return self._show({"ok": False, "source": "Barchart OnDemand",
                               "error": "provider_unavailable_or_invalid_response",
                               "error_type": type(exc).__name__, "orders_submitted": 0})

    async def external_source_status(self) -> str:
        """Report integration status without contacting paid or restricted services."""
        return self._show({
            "read_only": True, "orders_submitted": 0, "provider_calls": 0,
            "sources": {
                "Alpaca": "installed_existing_market_gateway",
                "Twelve Data": "installed_separate_existing_tool",
                "GDELT": "news_adapter_installed; availability_probed_per_request",
                "Barchart": (
                    "licensed_adapter_ready"
                    if os.getenv("BARCHART_ALGO_USE_APPROVED", "") == "1"
                    and bool(os.getenv("BARCHART_API_KEY", "").strip())
                    else "awaiting_algorithmic_use_entitlement_and_key"
                ),
                "TradingView": "non_display_automated_use_not_authorised",
                "StockAnalysis": "no_programmatic_API",
                "Yahoo Finance": "permissioned_API_or_export_required",
                "Finviz": "licensed_export_or_permission_required",
                "Investing.com": "no_public_API",
                "Trading 212 Social": "authorised_export_or_permission_required",
                "Trading 212 Community": "automated_monitoring_restricted",
                "Trading 212 Pie Library": "public_library_API_not_in_broker_gateway",
                "Stocktwits": "new_API_registrations_closed",
                "Reddit": "OAuth_and_app_approval_required",
            },
        })


    async def alpaca_news_catalysts(
        self, symbols_csv: str = "", lookback_hours: int = 24, top: int = 15
    ) -> str:
        """
        Retrieve timestamped market-news leads via the already authorised
        Alpaca Market Data News API. No third-party website scraping and no
        broker trading actions. Actual timeliness depends on account entitlement.
        :param symbols_csv: Optional comma-separated equity symbols, maximum 10.
        :param lookback_hours: Inclusive lookback, 1-72 hours.
        :param top: Maximum headlines, 1-25. One bounded request, no pagination.
        """
        from datetime import datetime, timedelta, timezone
        import re
        try:
            lookback_hours = max(1, min(72, int(lookback_hours)))
            top = max(1, min(25, int(top)))
        except (ValueError, TypeError, OverflowError):
            return self._show({
                "ok": False, "source": "Alpaca News API",
                "error": "invalid_parameters", "orders_submitted": 0,
            })
        symbols = self._symbols(symbols_csv, max_symbols=10)
        if any(not re.fullmatch(r"[A-Z0-9.^-]{1,15}", symbol) for symbol in symbols):
            return self._show({
                "ok": False, "source": "Alpaca News API",
                "error": "invalid_symbols", "orders_submitted": 0,
            })
        now = datetime.now(timezone.utc)
        start = (now - timedelta(hours=lookback_hours)).isoformat().replace("+00:00", "Z")
        params = {
            "start": start, "limit": top, "sort": "desc",
            "include_content": "false",
        }
        if symbols:
            params["symbols"] = ",".join(symbols)
        payload, error = await self._get(self.data_base, "/v1beta1/news", params=params)
        if error:
            return self._show({
                "ok": False, "source": "Alpaca News API",
                "error": "provider_error", "error_detail": str(error)[:240],
                "orders_submitted": 0,
            })
        if not isinstance(payload, dict) or not isinstance(payload.get("news"), list):
            return self._show({
                "ok": False, "source": "Alpaca News API",
                "error": "unexpected_provider_response", "orders_submitted": 0,
            })
        items = []
        for row in payload["news"][:top]:
            if not isinstance(row, dict):
                continue
            created = str(row.get("created_at") or "")
            age = None
            if created:
                try:
                    t = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    if t.tzinfo and t.utcoffset() is not None:
                        age = round((now - t.astimezone(timezone.utc)).total_seconds())
                except (ValueError, OverflowError):
                    pass
            items.append({
                "headline": str(row.get("headline") or "")[:260],
                "summary": str(row.get("summary") or "")[:500],
                "url": str(row.get("url") or "")[:800],
                "publisher": str(row.get("source") or "")[:100],
                "symbols": row.get("symbols") if isinstance(row.get("symbols"), list) else [],
                "published_at_utc": created,
                "updated_at_utc": str(row.get("updated_at") or ""),
                "age_seconds": age,
                "unverified_catalyst_lead": True,
                "broker_tradability_verified": False,
            })
        return self._show({
            "ok": True, "provider": "Alpaca",
            "source": "alpaca_news_api",
            "read_only_market_research": True,
            "orders_submitted": 0,
            "retrieved_at_utc": now.isoformat(),
            "lookback_hours": lookback_hours,
            "news_entitlement_delay_unverified": True,
            "filter_symbols": symbols,
            "count": len(items),
            "articles": items,
            "note": "News catalyst leads, not confirmed trading signals. "
                    "Check publication age, original reporting, momentum and T212 instrument.",
        })

"""Bind DeepSeek's DataSource seam to the existing Open WebUI Market Data Gateway.

Contract inspected in openwebui/tools/market_data_gateway.py at PR #17 commit
98b67aff: async Tools.candidate_scan(top=20, feed='iex') and
Tools.snapshots(symbols_csv, feed='iex'), both returning JSON strings.

The host must inject its *existing* configured Tools instance. This class owns
no API keys, HTTP clients, scheduler, broker connection or trade decisions.
All calls are made from a synchronous worker thread, never the WebUI event loop.
Market-cap filtering is not available from the inspected candidate_scan output;
that absence is explicitly reported rather than silently claimed as verified.
"""

import asyncio
import inspect
import json
import math
from collections.abc import Mapping


class InstalledAlpacaToolSource:
    def __init__(self, existing_market_data_tool, *, feed="iex", top=30):
        if feed not in ("iex", "delayed_sip"):
            raise ValueError("Only explicitly selected IEX/delayed-SIP feeds are supported")
        if not isinstance(top, int) or not 1 <= top <= 30:
            raise ValueError("Candidate top must be between 1 and 30")
        for method in ("candidate_scan", "snapshots"):
            if not callable(getattr(existing_market_data_tool, method, None)):
                raise TypeError(f"Existing market data tool missing {method}")
        self._tool = existing_market_data_tool
        self.feed = feed
        self.top = top

    def _call(self, method, **kwargs):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise RuntimeError("Run market data callbacks from a worker thread")
        result = getattr(self._tool, method)(**kwargs)
        if inspect.isawaitable(result):
            result = asyncio.run(result)
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{method} returned non-JSON/error text: {result[:200]}") from exc
        if not isinstance(result, Mapping):
            raise ValueError(f"{method} must return a JSON object")
        if result.get("provider") != "Alpaca" or result.get("feed") != self.feed:
            raise ValueError(f"{method} provider/feed identity mismatch")
        if result.get("readOnly") is not True:
            raise ValueError(f"{method} missing expected market-data-only provenance")
        return result

    @staticmethod
    def _valid_numeric(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)

    def movers(self, min_price=2.0, min_vol=500000, min_cap=100000000):
        """Discover candidates, preserving controller-supplied filter parameters.

        Unknown price/volume fields remain flagged, not asserted as compliant.
        Market cap cannot be verified by the current candidate_scan method.
        This is *discovery*, not an executable order qualification.
        """
        for name, value in (("min_price", min_price), ("min_vol", min_vol), ("min_cap", min_cap)):
            if not self._valid_numeric(value) or value < 0:
                raise ValueError(f"Invalid {name}")
        result = self._call("candidate_scan", top=self.top, feed=self.feed)
        rows = result.get("candidates")
        if not isinstance(rows, list):
            raise ValueError("Alpaca candidate_scan missing candidates array")
        provider_errors = {key: result[key] for key in ("moversError", "mostActiveError", "snapshotError") if result.get(key)}
        if not rows and provider_errors:
            raise RuntimeError(f"Alpaca candidate discovery unavailable: {provider_errors}")
        candidates = []
        for row in rows:
            if not isinstance(row, Mapping) or not isinstance(row.get("symbol"), str) or not row["symbol"].strip():
                raise ValueError("Invalid Alpaca candidate row/symbol")
            price, volume = row.get("price"), row.get("dayVolume")
            if self._valid_numeric(price) and price < min_price:
                continue
            if self._valid_numeric(volume) and volume < min_vol:
                continue
            candidate = dict(row)
            candidate.update(source="alpaca", feed=self.feed,
                discovery_only=True,
                price_filter_verified=self._valid_numeric(price),
                volume_filter_verified=self._valid_numeric(volume),
                market_cap_filter_verified=(min_cap == 0),
                requested_min_market_cap=min_cap,
                provider_errors=provider_errors)
            candidates.append(candidate)
        return candidates

    def quote(self, symbol):
        if not isinstance(symbol, str) or not symbol.strip() or "," in symbol:
            raise ValueError("A single nonempty symbol is required")
        symbol = symbol.strip().upper()
        result = self._call("snapshots", symbols_csv=symbol, feed=self.feed)
        rows = result.get("symbols")
        if not isinstance(rows, list) or len(rows) != 1:
            raise ValueError("Expected exactly one Alpaca snapshot")
        row = rows[0]
        if not isinstance(row, Mapping) or row.get("symbol") != symbol:
            raise ValueError("Alpaca snapshot symbol mismatch")
        if not any(self._valid_numeric(row.get(key)) for key in ("price", "bid", "ask")):
            raise ValueError("Alpaca snapshot contains no usable quote/price")
        return dict(row, source="alpaca", feed=self.feed, discovery_only=True)

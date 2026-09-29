"""
title: Trading 212 DEMO Gateway Candidate v0.3
author: Katie / OpenAI
description: Review-only candidate adding instrument caching and bounded read backoff. DEMO only.
version: 0.3.0-candidate
"""

import os
import json
import time
import asyncio
import random
import httpx

from t212_instrument_cache import InstrumentCache


class Tools:
    def __init__(self):
        self.base_url = "https://demo.trading212.com/api/v0"
        self.last_submission = None
        self.last_submission_time = 0.0
        self.instrument_cache = InstrumentCache()

    def _credentials(self):
        return (
            os.getenv("T212_DEMO_API_KEY", "").strip(),
            os.getenv("T212_DEMO_API_SECRET", "").strip(),
        )

    def _show(self, value):
        if isinstance(value, str):
            return value
        return json.dumps(value, indent=2, default=str)

    async def _request(self, method, path, json_body=None, retry_reads=True):
        key, secret = self._credentials()
        if not key or not secret:
            return None, "T212 DEMO credentials are not available to Open WebUI."

        method = method.upper()
        max_attempts = 4 if (retry_reads and method == "GET") else 1
        delay = 1.0

        for attempt in range(max_attempts):
            try:
                async with httpx.AsyncClient(
                    timeout=30.0,
                    auth=httpx.BasicAuth(key, secret),
                ) as client:
                    response = await client.request(
                        method,
                        f"{self.base_url}{path}",
                        json=json_body,
                        headers={
                            "Accept": "application/json",
                            "Content-Type": "application/json",
                        },
                    )

                try:
                    data = response.json()
                except Exception:
                    data = response.text

                if response.status_code == 429 and attempt + 1 < max_attempts:
                    retry_after = response.headers.get("Retry-After")
                    try:
                        wait = float(retry_after)
                    except Exception:
                        wait = delay + random.uniform(0, 0.25)
                    await asyncio.sleep(min(max(wait, 0.5), 15.0))
                    delay = min(delay * 2.0, 15.0)
                    continue

                if 500 <= response.status_code < 600 and attempt + 1 < max_attempts:
                    await asyncio.sleep(delay + random.uniform(0, 0.25))
                    delay = min(delay * 2.0, 15.0)
                    continue

                if response.is_error:
                    return None, f"T212 DEMO API error {response.status_code}: {data}"

                return data, None

            except Exception as exc:
                if attempt + 1 >= max_attempts:
                    return None, f"T212 DEMO connection error: {type(exc).__name__}: {exc}"
                await asyncio.sleep(delay)
                delay = min(delay * 2.0, 15.0)

        return None, "T212 DEMO request failed."

    async def _ensure_instrument_cache(self, force=False):
        payload = self.instrument_cache.load()
        if payload and self.instrument_cache.is_fresh(payload) and not force:
            return payload["instruments"], None, "disk"

        previous = payload.get("instruments", []) if payload else []
        data, error = await self._request("GET", "/equity/metadata/instruments")
        if error:
            if previous:
                return previous, None, "stale-disk-fallback"
            return None, error, None

        instruments = data if isinstance(data, list) else []
        self.instrument_cache.save_snapshot(instruments, previous)
        return instruments, None, "api-refresh"

    async def refresh_instrument_cache(self, force: bool = False) -> str:
        """
        Read-only. Refresh or reuse the T212 DEMO instrument cache.
        """
        instruments, error, source = await self._ensure_instrument_cache(force=bool(force))
        if error:
            return error
        diff = self.instrument_cache.latest_diff()
        return self._show({
            "environment": "DEMO",
            "gatewayVersion": "0.3.0-candidate",
            "cacheSource": source,
            "instrumentCount": len(instruments or []),
            "diffSummary": {
                "baselineWasPresent": diff.get("baselineWasPresent"),
                "addedCount": diff.get("addedCount"),
                "removedCount": diff.get("removedCount"),
                "changedCount": diff.get("changedCount"),
            },
            "liveTradingEnabled": False,
        })

    async def instrument_cache_status(self) -> str:
        """
        Read-only. Report cache state without calling Trading 212.
        """
        payload = self.instrument_cache.load()
        return self._show({
            "environment": "DEMO",
            "gatewayVersion": "0.3.0-candidate",
            "cacheExists": bool(payload),
            "cacheFresh": self.instrument_cache.is_fresh(payload),
            "instrumentCount": len((payload or {}).get("instruments", [])),
            "fetchedAtEpoch": (payload or {}).get("fetchedAtEpoch"),
            "liveTradingEnabled": False,
        })

    async def new_on_t212(self, limit: int = 100) -> str:
        """
        Read-only. Return instruments added since the previous instrument-master snapshot.
        """
        limit = max(1, min(int(limit), 500))
        _, error, source = await self._ensure_instrument_cache(force=False)
        if error:
            return error
        diff = self.instrument_cache.latest_diff()
        added = diff.get("added", []) if isinstance(diff, dict) else []
        return self._show({
            "environment": "DEMO",
            "cacheSource": source,
            "baselineWasPresent": diff.get("baselineWasPresent"),
            "newCount": len(added),
            "newInstruments": added[:limit],
            "liveTradingEnabled": False,
        })

    async def find_instrument(self, query: str) -> str:
        """
        Search cached Trading 212 DEMO instrument metadata.
        """
        query = (query or "").strip()
        if not query:
            return "Instrument query is empty."

        _, error, source = await self._ensure_instrument_cache(force=False)
        if error:
            return error

        matches = self.instrument_cache.search(query, limit=10)
        if not matches:
            return f"No T212 DEMO instrument matched '{query}'."

        rows = []
        for inst in matches:
            rows.append({
                "name": inst.get("name"),
                "shortName": inst.get("shortName"),
                "ticker": inst.get("ticker"),
                "currencyCode": inst.get("currencyCode"),
                "type": inst.get("type"),
                "extendedHours": inst.get("extendedHours"),
                "maxOpenQuantity": inst.get("maxOpenQuantity"),
                "cacheSource": source,
            })
        return self._show(rows)

    # IMPORTANT:
    # Existing v0.2.0 broker/account/order methods are intentionally not duplicated here.
    # This candidate is for code review and merge into the current gateway only.
    # POST order methods must retain single-attempt / no-blind-retry behaviour.

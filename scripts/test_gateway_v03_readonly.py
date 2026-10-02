#!/usr/bin/env python3
"""DEMO-only validation for self-contained T212 DEMO gateway v0.3 candidate."""
import asyncio, importlib.util, json, os, sys, tempfile
from pathlib import Path

MODULE=Path(sys.argv[1] if len(sys.argv)>1 else "/tmp/t212-test/trading212_demo_gateway_v03_selfcontained.py")
spec=importlib.util.spec_from_file_location("gw",MODULE)
gw=importlib.util.module_from_spec(spec); spec.loader.exec_module(gw)

async def main():
    if not os.getenv("T212_DEMO_API_KEY") or not os.getenv("T212_DEMO_API_SECRET"):
        raise SystemExit("T212 DEMO credentials not present in environment")
    with tempfile.TemporaryDirectory() as td:
        tool=gw.Tools()
        tool.instrument_cache=gw.InstrumentCache(
            cache_path=str(Path(td)/"cache.json"),
            diff_path=str(Path(td)/"diff.json"),
            ttl_seconds=86400,
        )
        first=json.loads(await tool.refresh_instrument_cache(force=True))
        assert first["environment"]=="DEMO"
        assert first["liveTradingEnabled"] is False
        assert first["instrumentCount"]>1000
        assert first["diffSummary"]["addedCount"]==0
        status=json.loads(await tool.instrument_cache_status())
        assert status["cacheExists"] and status["cacheFresh"]
        fetches_before=status["metadataFetchesThisProcess"]
        searches=[json.loads(await tool.find_instrument("Apple")) for _ in range(10)]
        assert all(isinstance(search,list) and len(search)>=1 for search in searches)
        status_after=json.loads(await tool.instrument_cache_status())
        assert status_after["metadataFetchesThisProcess"]==fetches_before
        search=searches[0]
        new=json.loads(await tool.new_on_t212())
        assert new["newCount"]==0
        second=json.loads(await tool.refresh_instrument_cache(force=False))
        assert second["cacheSource"]=="disk"
        print("GATEWAY_V03_DEMO_TEST=PASS")
        print("INSTRUMENT_COUNT="+str(first["instrumentCount"]))
        print("SEARCH_MATCHES="+str(len(search)))
        print("TEN_LOOKUPS_METADATA_REDOWNLOADS=0")
        print("CACHE_SOURCE_SECOND="+second["cacheSource"])
        print("LIVE_TRADING_ENABLED=False")
        print("ORDERS_SUBMITTED=0")

if __name__=="__main__": asyncio.run(main())

"""Read-only integration test for T212 DEMO instrument metadata/cache."""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

import httpx

sys.path.insert(0, "/tmp/t212-test")
from t212_instrument_cache import InstrumentCache


async def main():
    key=os.getenv("T212_DEMO_API_KEY","").strip()
    secret=os.getenv("T212_DEMO_API_SECRET","").strip()
    if not key or not secret:
        raise SystemExit("T212 DEMO credentials missing in container env")

    with tempfile.TemporaryDirectory(prefix="t212-cache-readonly-") as td:
        cache=InstrumentCache(
            cache_path=str(Path(td)/"instruments.json"),
            diff_path=str(Path(td)/"diff.json"),
            ttl_seconds=86400,
        )
        async with httpx.AsyncClient(timeout=30.0, auth=httpx.BasicAuth(key, secret)) as client:
            r=await client.get(
                "https://demo.trading212.com/api/v0/equity/metadata/instruments",
                headers={"Accept":"application/json"},
            )
        print("HTTP_STATUS="+str(r.status_code))
        if r.is_error:
            print("ERROR_BODY="+r.text[:500])
            raise SystemExit(1)
        data=r.json()
        if not isinstance(data,list):
            raise SystemExit("Unexpected metadata response shape")
        print("INSTRUMENT_COUNT="+str(len(data)))
        diff1=cache.save_snapshot(data,[])
        print("BASELINE_PRESENT="+str(diff1.get("baselineWasPresent")))
        print("FIRST_ADDED_COUNT="+str(diff1.get("addedCount")))
        payload=cache.load()
        print("CACHE_EXISTS="+str(bool(payload)))
        print("CACHE_FRESH="+str(cache.is_fresh(payload)))
        sample = data[0] if data else {}
        query = str(sample.get("ticker") or sample.get("name") or "")
        matches=cache.search(query,limit=3) if query else []
        print("LOCAL_SEARCH_MATCHES="+str(len(matches)))
        diff2=cache.save_snapshot(data,data)
        print("SECOND_ADDED_COUNT="+str(diff2.get("addedCount")))
        print("SECOND_REMOVED_COUNT="+str(diff2.get("removedCount")))
        print("SECOND_CHANGED_COUNT="+str(diff2.get("changedCount")))
        print("READ_ONLY_CACHE_TEST=PASS")

if __name__=="__main__":
    asyncio.run(main())
import importlib.util
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock


MODULE = Path(__file__).with_name("refresh_t212_cache_worker.py")
if not MODULE.exists():
    MODULE = Path(__file__).parents[1] / "scripts" / "refresh_t212_cache_worker.py"
SPEC = importlib.util.spec_from_file_location("cache_worker", MODULE)
WORKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WORKER)


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def _http_error(code=429, retry_after=None):
    headers = {}
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError(
        "https://demo.trading212.com/api/v0/equity/metadata/instruments",
        code,
        "retryable",
        headers,
        None,
    )


class CacheWorkerAcceptanceTests(unittest.TestCase):
    def test_bounded_deterministic_429_retry(self):
        attempts = []
        sleeps = []

        def urlopen(req, timeout=30):
            attempts.append(timeout)
            if len(attempts) < 3:
                raise _http_error(429)
            return _Response([{"ticker": "ABC_US_EQ"}])

        with mock.patch.object(WORKER.urllib.request, "urlopen", side_effect=urlopen):
            with mock.patch.object(WORKER.time, "sleep", side_effect=sleeps.append):
                result = WORKER.fetch_instruments(object(), max_attempts=4)

        self.assertEqual(result, [{"ticker": "ABC_US_EQ"}])
        self.assertEqual(len(attempts), 3)
        self.assertEqual(sleeps, [50.0, 50.0])

    def test_worker_reuses_recent_tool_snapshot_without_metadata_call(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            with mock.patch.multiple(WORKER,DATA_DIR=root,CACHE=root/'t212_instrument_cache.json',DIFF=root/'diff.json',LOCK=root/'t212_instrument_cache.lock',STATUS=root/'status.json'):
                WORKER.atomic(WORKER.CACHE,{'environment':'DEMO','fetchedAtEpoch':WORKER.time.time(),'instruments':[{'ticker':'SAFE_US_EQ'}]})
                with mock.patch.dict(os.environ,{'T212_DEMO_API_KEY':'synthetic','T212_DEMO_API_SECRET':'synthetic'}), mock.patch.object(WORKER.urllib.request,'urlopen') as request:
                    self.assertEqual(WORKER.main(),0)
                    request.assert_not_called()
                self.assertEqual(json.loads(WORKER.STATUS.read_text())['cache_source'],'disk-cooldown')

    def test_long_provider_cooldown_aborts_without_early_retry(self):
        calls=[]
        def request(*args, **kwargs):
            calls.append(1)
            raise _http_error(429,'300')
        with mock.patch.object(WORKER.urllib.request,'urlopen',side_effect=request):
            with mock.patch.object(WORKER.time,'sleep') as sleep:
                with self.assertRaises(urllib.error.HTTPError):WORKER.fetch_instruments(object())
        self.assertEqual(len(calls),1);sleep.assert_not_called()

    def test_retry_after_is_respected(self):
        self.assertEqual(WORKER._retry_delay({"Retry-After": "9"}, 0), 9.0)
        self.assertEqual(WORKER._retry_delay({"Retry-After": "99"}, 0), 99.0)
        self.assertEqual(WORKER._retry_delay({}, 2), 4.0)

    def test_existing_cache_survives_provider_429_without_order_path(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with mock.patch.multiple(
                WORKER,
                DATA_DIR=root,
                CACHE=root / "t212_instrument_cache.json",
                DIFF=root / "t212_instrument_diff.json",
                LOCK=root / "t212_instrument_cache.lock",
                STATUS=root / "t212_instrument_cache_status.json",
            ):
                WORKER.atomic(
                    WORKER.CACHE,
                    {
                        "environment": "DEMO",
                        "fetchedAtEpoch": 1,
                        "instruments": [{"ticker": "SAFE_US_EQ"}],
                    },
                )
                with mock.patch.dict(
                    os.environ,
                    {"T212_DEMO_API_KEY": "placeholder", "T212_DEMO_API_SECRET": "placeholder"},
                    clear=False,
                ):
                    with mock.patch.object(
                        WORKER.urllib.request,
                        "urlopen",
                        side_effect=_http_error(429),
                    ):
                        with mock.patch.object(WORKER.time, "sleep"):
                            rc = WORKER.main()

                status = json.loads(WORKER.STATUS.read_text(encoding="utf-8"))
                cache = json.loads(WORKER.CACHE.read_text(encoding="utf-8"))
                self.assertEqual(rc, 0)
                self.assertTrue(status["degraded"])
                self.assertEqual(status["cache_source"], "stale-disk-fallback")
                self.assertEqual(status["orders_submitted"], 0)
                self.assertFalse(status["live_trading_enabled"])
                self.assertEqual(cache["instruments"], [{"ticker": "SAFE_US_EQ"}])


if __name__ == "__main__":
    unittest.main()

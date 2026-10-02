import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from worker.discovery_adapter import DiscoveryInputError, load_snapshot
from worker.produce_market_snapshot import SnapshotProductionError, produce_snapshot


NOW = datetime(2026, 10, 2, 14, 30, tzinfo=timezone.utc)
NOW_EPOCH = NOW.timestamp()


class FakeGateway:
    def __init__(self, *, stale_only=False, bars_available=True):
        self.stale_only = stale_only
        self.bars_available = bars_available
        self.calls = []

    async def market_clock(self):
        self.calls.append(("market_clock",))
        return json.dumps(
            {
                "is_open": True,
                "timestamp": NOW.isoformat(),
                "next_close": "2026-10-02T20:00:00+00:00",
            }
        )

    async def candidate_scan(self, top=30, feed="iex"):
        self.calls.append(("candidate_scan", top, feed))
        fresh_ts = "2026-10-02T14:29:30+00:00"
        if self.stale_only:
            fresh_ts = "2026-10-02T13:00:00+00:00"
        return json.dumps(
            {
                "provider": "Alpaca",
                "feed": feed,
                "candidateCount": 2,
                "candidates": [
                    {
                        "symbol": "ABC",
                        "price": 10,
                        "dayVolume": 100000,
                        "previousVolume": 50000,
                        "previousClose": 8,
                        "bid": 9.9,
                        "ask": 10.1,
                        "quoteTimestamp": fresh_ts,
                        "tradeTimestamp": fresh_ts,
                    },
                    {
                        "symbol": "OLD",
                        "price": 5,
                        "dayVolume": 1000,
                        "previousVolume": 900,
                        "previousClose": 4,
                        "bid": 4.9,
                        "ask": 5.1,
                        "quoteTimestamp": "2026-10-02T13:00:00+00:00",
                        "tradeTimestamp": "2026-10-02T13:00:00+00:00",
                    },
                ],
                "moversError": None,
                "mostActiveError": None,
                "snapshotError": None,
            }
        )

    async def bars(self, symbols_csv, **kwargs):
        self.calls.append(("bars", symbols_csv, kwargs))
        if not self.bars_available:
            return "Alpaca data API error 403: plan restriction"
        return json.dumps(
            {
                "bars": {
                    "ABC": [{"v": 40000}, {"v": 60000}],
                    "OLD": [{"v": 900}],
                }
            }
        )


class MarketSnapshotProducerTests(unittest.IsolatedAsyncioTestCase):
    async def test_broad_snapshot_has_row_freshness_and_volume_baseline(self):
        gateway = FakeGateway()
        snapshot = await produce_snapshot(
            gateway,
            now_epoch=NOW_EPOCH,
            max_age_seconds=300,
        )
        self.assertEqual(snapshot["source_kind"], "live_provider")
        self.assertFalse(snapshot["fixture"])
        self.assertTrue(snapshot["row_freshness_enforced"])
        self.assertEqual(snapshot["input_candidate_count"], 2)
        self.assertEqual(snapshot["accepted_row_count"], 1)
        self.assertEqual(snapshot["stale_rejected_count"], 1)
        row = snapshot["rows"][0]
        self.assertEqual(row["symbol"], "ABC")
        self.assertEqual(row["avg20_volume"], 50000)
        self.assertEqual(row["volume_baseline_source"], "completed_20d_bars")
        self.assertEqual(row["observation_age_seconds"], 30)
        self.assertGreater(row["session_elapsed_fraction"], 0)
        self.assertEqual(snapshot["orders_submitted"], 0)
        self.assertFalse(snapshot["live_trading_enabled"])
        self.assertFalse(any(call[0] in {"post", "order"} for call in gateway.calls))

    async def test_missing_bars_uses_explicit_previous_session_fallback(self):
        snapshot = await produce_snapshot(
            FakeGateway(bars_available=False),
            now_epoch=NOW_EPOCH,
            max_age_seconds=300,
        )
        row = snapshot["rows"][0]
        self.assertEqual(row["avg20_volume"], 50000)
        self.assertEqual(row["volume_baseline_source"], "previous_session_fallback")
        self.assertIn("403", snapshot["historical_bars_error"])

    async def test_all_stale_candidates_fail_closed(self):
        with self.assertRaises(SnapshotProductionError):
            await produce_snapshot(
                FakeGateway(stale_only=True),
                now_epoch=NOW_EPOCH,
                max_age_seconds=300,
            )


class SnapshotFreshnessGateTests(unittest.TestCase):
    def _write(self, root, payload):
        path = Path(root) / "snapshot.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_live_snapshot_requires_row_level_freshness(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._write(
                td,
                {
                    "source": "alpaca:test",
                    "source_kind": "live_provider",
                    "fixture": False,
                    "generated_at": NOW_EPOCH,
                    "row_freshness_enforced": True,
                    "rows": [
                        {
                            "symbol": "ABC",
                            "observation_age_seconds": 30,
                        }
                    ],
                },
            )
            result = load_snapshot(path, max_age_seconds=300, now_epoch=NOW_EPOCH)
            self.assertEqual(result["source_kind"], "live_provider")
            self.assertFalse(result["fixture"])

    def test_closed_market_fixture_is_rejected_by_runtime_default(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._write(
                td,
                {
                    "source": "fixture:closed-market",
                    "source_kind": "closed_market_fixture",
                    "fixture": True,
                    "generated_at": NOW_EPOCH,
                    "row_freshness_enforced": True,
                    "rows": [
                        {
                            "symbol": "ABC",
                            "observation_age_seconds": 0,
                        }
                    ],
                },
            )
            with self.assertRaises(DiscoveryInputError):
                load_snapshot(path, max_age_seconds=300, now_epoch=NOW_EPOCH)
            result = load_snapshot(
                path,
                max_age_seconds=300,
                now_epoch=NOW_EPOCH,
                allow_fixture=True,
            )
            self.assertTrue(result["fixture"])

    def test_stale_row_is_rejected_even_when_file_is_new(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._write(
                td,
                {
                    "source": "alpaca:test",
                    "source_kind": "live_provider",
                    "fixture": False,
                    "generated_at": NOW_EPOCH,
                    "row_freshness_enforced": True,
                    "rows": [
                        {
                            "symbol": "ABC",
                            "observation_age_seconds": 301,
                        }
                    ],
                },
            )
            with self.assertRaises(DiscoveryInputError):
                load_snapshot(path, max_age_seconds=300, now_epoch=NOW_EPOCH)


if __name__ == "__main__":
    unittest.main()


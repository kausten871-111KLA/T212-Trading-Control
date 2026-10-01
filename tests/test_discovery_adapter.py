import json
import tempfile
import unittest
from pathlib import Path

from worker.discovery_adapter import DiscoveryInputError, load_instrument_cache, load_snapshot, normalize_rows


class DiscoveryAdapterTests(unittest.TestCase):
    def test_stale_market_input_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "snapshot.json"
            path.write_text(json.dumps({
                "source": "fixture",
                "generated_at": 1000,
                "rows": [{"symbol": "ABC"}],
            }), encoding="utf-8")
            self.assertEqual(load_snapshot(path, max_age_seconds=100, now_epoch=1050)["source"], "fixture")
            with self.assertRaises(DiscoveryInputError):
                load_snapshot(path, max_age_seconds=100, now_epoch=1200)

    def test_non_demo_instrument_cache_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "cache.json"
            path.write_text(json.dumps({
                "environment": "OTHER",
                "fetchedAtEpoch": 1000,
                "instruments": [{"ticker": "ABC_US_EQ"}],
            }), encoding="utf-8")
            with self.assertRaises(DiscoveryInputError):
                load_instrument_cache(path, now_epoch=1001)

    def test_instrument_mapping_blocks_unsupported_type(self):
        rows = [
            {"symbol":"ABC","price":10,"change_pct":12,"rel_vol":3,"spread_pct":1,"dollar_vol":2000000},
            {"symbol":"XYZ","price":5,"change_pct":20,"rel_vol":4,"spread_pct":1,"dollar_vol":2000000},
        ]
        instruments = [
            {"ticker":"ABC_US_EQ","type":"STOCK","status":"active"},
            {"ticker":"XYZ_US_EQ","type":"WARRANT","status":"active"},
        ]
        by_symbol = {row["symbol"]: row for row in normalize_rows(rows, instruments)}
        self.assertEqual(by_symbol["ABC"]["t212_ticker"], "ABC_US_EQ")
        self.assertTrue(by_symbol["ABC"]["tradable"])
        self.assertFalse(by_symbol["XYZ"]["tradable"])


if __name__ == "__main__":
    unittest.main()

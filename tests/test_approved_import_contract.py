"""Offline approved-import provenance, stale-label and dedupe contract tests."""
import importlib.util
import json
import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, main
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "openwebui/tools/market_data_gateway.py"
spec = importlib.util.spec_from_file_location("market_gateway_import_contract", SOURCE)
gateway = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gateway)


class ImportContractTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tool = gateway.Tools()
        self.now = datetime.now(timezone.utc)
        self.stamp = self.now.isoformat()

    @contextmanager
    def fixture(self, rows, *, symlink_root=False):
        payload = {
            "source": "reddit",
            "approved_for_automated_research": True,
            "collected_at_utc": self.stamp,
            "records": rows,
        }
        data = json.dumps(payload)
        with patch.dict(os.environ, {"MARKET_IMPORT_APPROVED_SOURCES": "reddit"}):
            with patch.object(Path, "is_symlink",
                              lambda p: symlink_root and p.name == "market_research_imports"):
                with patch.object(Path, "is_file", lambda p: p.name == "reddit.json"):
                    with patch.object(Path, "stat",
                                      lambda p: SimpleNamespace(st_size=len(data))):
                        with patch.object(Path, "read_text", lambda p, **kw: data):
                            yield

    async def test_exact_duplicate_removed_but_updated_observation_retained(self):
        a = {"origin": "approved_export", "observed_at_utc": self.stamp,
             "symbol": "AAA", "price": 10, "text": "research only"}
        b = dict(a, price=11)
        bad = {"observed_at_utc": self.stamp, "symbol": "BBB"}
        future = dict(a, observed_at_utc=(self.now + timedelta(hours=1)).isoformat())
        naive = dict(a, observed_at_utc="2026-10-26T12:00:00")
        with self.fixture([a, a, b, bad, future, naive]):
            out = json.loads(await self.tool.approved_source_imports("reddit"))
        self.assertTrue(out["ok"])
        self.assertEqual(out["count"], 2)
        self.assertEqual(out["records_exact_duplicates"], 1)
        self.assertEqual(out["records_invalid_provenance"], 3)
        self.assertEqual([r["price"] for r in out["records"]], ["10", "11"])
        self.assertTrue(all(r["untrusted_external_text"] for r in out["records"]))
        self.assertTrue(all("record_observed_at_utc" in r for r in out["records"]))
        self.assertTrue(out["not_live_provider_connection"])
        self.assertEqual(out["orders_submitted"], 0)

    async def test_stale_observation_labeled_not_silently_treated_as_current(self):
        old = (self.now - timedelta(days=2)).isoformat()
        with self.fixture([{"origin": "approved_export",
                            "observed_at_utc": old, "symbol": "CCC"}]):
            out = json.loads(await self.tool.approved_source_imports("reddit"))
        self.assertTrue(out["ok"])
        self.assertFalse(out["source_file_age_stale_over_24h"])
        self.assertTrue(out["records"][0]["record_stale_over_24h"])
        self.assertGreater(out["records"][0]["record_age_seconds"], 86400)
        self.assertEqual(out["freshness_label_ttl_seconds"], 86400)

    async def test_invalid_records_fail_closed(self):
        with self.fixture([{}, {"origin": "approved_export",
                                "observed_at_utc": "not-a-date"}]):
            out = json.loads(await self.tool.approved_source_imports("reddit"))
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "no_valid_import_records")
        self.assertEqual(out["records_invalid_provenance"], 2)
        self.assertEqual(out["records"], [])

    async def test_symlinked_import_root_is_rejected_before_read(self):
        with self.fixture([], symlink_root=True):
            out = json.loads(await self.tool.approved_source_imports("reddit"))
        self.assertEqual(out["error"], "approved_import_directory_symlink")
        self.assertEqual(out["file_reads"], 0)

    async def test_nonfinite_numeric_value_never_enters_strict_json(self):
        row = {"origin": "approved_export", "observed_at_utc": self.stamp,
               "symbol": "DDD", "volume": float("nan"), "price": float("inf")}
        with self.fixture([row]):
            raw = await self.tool.approved_source_imports("reddit")
        out = json.loads(raw, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
        self.assertTrue(out["ok"])
        self.assertNotIn("volume", out["records"][0])
        self.assertNotIn("price", out["records"][0])
        self.assertEqual(out["records"][0]["symbol"], "DDD")

    async def test_top_limit_applies_after_exact_dedupe(self):
        a = {"origin": "approved_export", "observed_at_utc": self.stamp,
             "symbol": "EEE"}
        b = dict(a, symbol="FFF")
        with self.fixture([a, a, a, b]):
            out = json.loads(await self.tool.approved_source_imports("reddit", top=2))
        self.assertEqual(out["count"], 2)
        self.assertEqual(out["records_exact_duplicates"], 2)
        self.assertEqual(out["records_examined"], 4)


if __name__ == "__main__":
    main()

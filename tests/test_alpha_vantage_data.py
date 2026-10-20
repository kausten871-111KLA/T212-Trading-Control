"""Offline tests: no provider or broker network calls."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from runtime.deepseek.alpha_vantage_data import daily_bars

NOW = 1792530000

def response():
    payload = {
        "Meta Data": {"2. Symbol": "IBM"},
        "Time Series (Daily)": {
            "2026-10-19": {"1. open": "10", "2. high": "11", "3. low": "9",
                           "4. close": "10.5", "5. volume": "250"},
            "2026-10-16": {"1. open": "9", "2. high": "10", "3. low": "8",
                           "4. close": "9.8", "5. volume": "190"},
        }
    }
    return io.BytesIO(json.dumps(payload).encode())

class DailyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.key=Path(self.temp.name)/"keys.env"
        self.key.write_text("ALPHAVANTAGE_API_KEY=TEST12345678\n")
        self.db=Path(self.temp.name)/"quota.sqlite3"
        self.urls=[]

    def fetch(self,url,timeout):
        self.urls.append(url)
        return response()

    def query(self,symbol,**kw):
        return daily_bars(symbol,key_file=self.key,db_file=self.db,
                          fetch=self.fetch,clock=lambda:NOW,**kw)

    def test_key_not_in_returned_data(self):
        result=self.query("IBM")
        self.assertTrue(result["ok"])
        self.assertEqual(result["latest_date"],"2026-10-19")
        self.assertEqual(len(result["bars"]),2)
        self.assertNotIn("TEST12345678",json.dumps(result))
        self.assertEqual(len(self.urls),1)

    def test_cached_second_call_no_extra_credit(self):
        self.assertTrue(self.query("TSCO.LON")["ok"])
        self.assertTrue(self.query("TSCO.LON")["cached"])
        self.assertEqual(len(self.urls),1)

    def test_symbol_input_rejected(self):
        for name in ("IBM;shutdown", "../etc/passwd", "HTTP://X", "IBM&apikey=X"):
            self.assertEqual(self.query(name)["error"],"invalid_symbol")
        self.assertEqual(len(self.urls),0)

    def test_missing_key(self):
        self.key.unlink()
        self.assertEqual(self.query("IBM")["error"],"alpha_vantage_key_not_configured")

    def test_local_daily_credit_budget(self):
        for index in range(25):
            self.assertTrue(self.query("SYM"+str(index))["ok"])
        result=self.query("SYM25")
        self.assertEqual(result["error"],"local_free_daily_quota_exhausted")
        self.assertEqual(len(self.urls),25)

    def test_provider_notice_does_not_claim_market_data(self):
        def notice(url,timeout):
            return io.BytesIO(b'{"Information":"premium-only"}')
        result=daily_bars("BMW.DEX",key_file=self.key,db_file=self.db,
                          fetch=notice,clock=lambda:NOW)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"],"provider_entitlement_or_quota_notice")
        self.assertNotIn("premium-only",json.dumps(result))

if __name__=="__main__":
    unittest.main()

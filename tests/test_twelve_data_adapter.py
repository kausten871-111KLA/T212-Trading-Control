"""Tests for no-secret Twelve Data adapter: no external HTTP requests."""
from __future__ import annotations
from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs,urlparse

from runtime.deepseek.twelve_data_adapter import query, _key, MAX_LOCAL_PER_MINUTE


class FakeResponse:
    def __init__(self,obj,headers=None):
        self.data=json.dumps(obj).encode()
        self.headers=headers or {"api-credits-used":"1","api-credits-left":"7"}
    def read(self,n=300000):
        return self.data[:n]
    def __enter__(self):return self
    def __exit__(self,*args):return False


class TwelveDataTest(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        p=Path(temp.name)
        self.key_file=p/"data-api.env"
        self.key_file.write_text("TWELVEDATA_API_KEY=EXAMPLEkey1234567890\n")
        self.db_file=p/"quota.sqlite3"
        self.clock=lambda:1792611000
        self.calls=[]
        self.sample={"symbol":"TSCO","exchange":"LSE","mic_code":"XLON",
            "currency":"GBX","datetime":"2026-10-21","close":"310.50",
            "volume":"16507200","previous_close":"306.10","percent_change":"1.44"}

    def run_query(self,operation,**kwargs):
        def fetch(request,timeout):
            self.calls.append(request)
            self.assertNotIn("EXAMPLEkey",request.full_url)
            self.assertEqual(request.get_header("Authorization"),"apikey EXAMPLEkey1234567890")
            self.assertEqual(request.get_method(),"GET")
            path=urlparse(request.full_url).path
            if path=="/quote":payload=self.sample
            elif path=="/time_series":
                payload={
                    "meta":{"symbol":"TSCO","exchange":"LSE","mic_code":"XLON",
                            "currency":"GBX","exchange_timezone":"Europe/London",
                            "interval":kwargs.get("interval","1day")},
                    "values":[{"datetime":"2026-10-21","open":"308.00","high":"312.00",
                               "low":"306.00","close":"310.50","volume":"16507200"}],
                    "status":"ok",
                }
            elif path=="/symbol_search":
                payload={"data":[{"symbol":"TSCO","instrument_name":"TESCO PLC",
                            "exchange":"LSE","mic_code":"XLON","country":"United Kingdom",
                            "currency":"GBX","instrument_type":"Common Stock"}],"status":"ok"}
            else:payload={"plan":"Basic","credits_left":7}
            return FakeResponse(payload)
        return query(operation,symbol="TSCO",key_file=self.key_file,
            db_file=self.db_file,clock=self.clock,fetch=fetch,**kwargs)

    def test_quote_preserves_exchange_and_currency(self):
        r=self.run_query("quote",exchange="LSE")
        self.assertTrue(r["ok"])
        self.assertEqual(r["mic_code"],"XLON")
        self.assertEqual(r["currency"],"GBX")
        self.assertEqual(r["close"],"310.50")
        self.assertFalse(r["execution_quote"])

    def test_cache_does_not_consume_extra_api_call(self):
        a=self.run_query("quote")
        b=self.run_query("quote")
        self.assertEqual(len(self.calls),1)
        self.assertFalse(a["cached"])
        self.assertTrue(b["cached"])

    def test_different_exchange_separate_cache(self):
        self.run_query("quote",exchange="LSE")
        self.run_query("quote",exchange="XETRA")
        self.assertEqual(len(self.calls),2)

    def test_time_series_daily_does_not_fake_utc(self):
        result=self.run_query("time_series",exchange="LSE")
        self.assertEqual(result["bar_time_basis"],"exchange_local_date")
        self.assertEqual(result["values"][0]["datetime"],"2026-10-21")
        self.assertEqual(result["meta"]["currency"],"GBX")
        args=parse_qs(urlparse(self.calls[0].full_url).query)
        self.assertNotIn("timezone",args)

    def test_time_series_intraday_explicit_utc(self):
        result=self.run_query("time_series",interval="5min")
        self.assertEqual(result["bar_time_basis"],"UTC_requested_provider_series")
        args=parse_qs(urlparse(self.calls[0].full_url).query)
        self.assertEqual(args["timezone"],["UTC"])
        self.assertEqual(args["interval"],["5min"])

    def test_search_includes_exchange_and_type(self):
        r=self.run_query("symbol_search")
        self.assertEqual(r["matches"][0]["mic_code"],"XLON")
        self.assertEqual(r["matches"][0]["instrument_type"],"Common Stock")

    def test_usage_costs_credit(self):
        r=self.run_query("api_usage")
        self.assertEqual(r["usage"]["plan"],"Basic")
        self.assertEqual(len(self.calls),1)

    def test_rate_guard_allows_max_six_requests(self):
        for i in range(MAX_LOCAL_PER_MINUTE):
            self.run_query("quote",exchange="LSE"+str(i))
        r=self.run_query("quote",exchange="DIFFERENT")
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"],"local_twelve_data_credit_budget_exhausted")
        self.assertEqual(len(self.calls),MAX_LOCAL_PER_MINUTE)

    def test_rejected_injection_does_not_use_credits(self):
        for s in ["TSCO;rm -rf /","https://evil","TSCO?apikey=hack",""]:
            r=query("quote",symbol=s,key_file=self.key_file,
                    db_file=self.db_file,clock=self.clock,
                    fetch=lambda *a,**k: self.fail("should not fetch"))
            self.assertFalse(r["ok"])
        self.assertEqual(len(self.calls),0)

    def test_api_key_missing_no_network(self):
        r=query("quote",symbol="AAPL",key_file=Path("/does/not/exist"),
                db_file=self.db_file,clock=self.clock,
                fetch=lambda *a,**k: self.fail("unexpected network"))
        self.assertEqual(r["error"],"twelve_data_key_not_configured")

    def test_http_403_is_not_plan_success(self):
        from urllib.error import HTTPError
        def fail(*args,**kw):
            raise HTTPError("https://api.twelvedata.com/quote",403,"Forbidden",None,None)
        r=query("quote",symbol="TSCO",key_file=self.key_file,db_file=self.db_file,
                clock=self.clock,fetch=fail)
        self.assertFalse(r["ok"])
        self.assertTrue(r["entitlement_or_plan_may_be_required"])

    def test_provider_error_403_does_not_leak_secret(self):
        def fail(*args,**kw):
            return FakeResponse({"status":"error","code":403,
                     "message":"key EXAMPLEkey1234567890 must upgrade"})
        r=query("quote",symbol="TSCO",key_file=self.key_file,db_file=self.db_file,
                clock=self.clock,fetch=fail)
        self.assertFalse(r["ok"])
        self.assertNotIn("EXAMPLEkey",json.dumps(r))

    def test_unknown_operation_rejected(self):
        r=self.run_query("time_series_cross")
        self.assertFalse(r["ok"])
        self.assertEqual(len(self.calls),0)

    def test_negative_outputsize_rejected(self):
        r=self.run_query("time_series",outputsize=-1)
        self.assertEqual(r["error"],"invalid_outputsize")

    def test_exchange_id_not_confused_by_same_ticker(self):
        self.run_query("quote",exchange="LSE")
        self.run_query("quote",exchange="NASDAQ")
        urls=[urlparse(request.full_url) for request in self.calls]
        self.assertEqual(len(urls),2)
        self.assertNotEqual(urls[0].query,urls[1].query)

if __name__=="__main__":
    unittest.main()

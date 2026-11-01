import unittest
from runtime.deepseek.scheduled_source_receipts import audit_saved_web_tools


def chat(args, output, name="fetch_url", call_id="one", role="assistant"):
    call={"type":"function_call","name":name,"call_id":call_id,
          "arguments":args,"status":"completed"}
    result={"type":"function_call_output","call_id":call_id,"output":output,
            "status":"completed"}
    return {"history":{"messages":{"a":{"role":role,"output":[call,result]}}}}


class ScheduledSourceReceiptsTests(unittest.TestCase):
    def test_verified_success_not_inferred_from_plain_tool_success(self):
        c=chat('{"url":"https://stockanalysis.com/markets/gainers/"}',
               [{"type":"input_text","text":"US gainers BOLT 30%"}])
        r=audit_saved_web_tools(c)[0]
        self.assertEqual(r["source_host"],"stockanalysis.com")
        self.assertEqual(r["source_path"],"/markets/gainers/")
        self.assertEqual(r["status"],"result_received_unvalidated")
        self.assertFalse(r["market_rows_verified"])

    def test_yahoo_page_with_error_and_data_is_degraded(self):
        c=chat('{"url":"https://uk.finance.yahoo.com/markets/stocks/gainers/"}',
               [{"type":"input_text","text":"Something went wrong; ORCP.L +19%"}])
        r=audit_saved_web_tools(c)[0]
        self.assertEqual(r["status"],"degraded_result")
        self.assertIn("something went wrong",r["error_markers"])

    def test_no_mention_in_prompt_counts_as_call(self):
        c={"history":{"messages":{"u":{"role":"user","content":"fetch_url StockAnalysis"}}}}
        self.assertEqual(audit_saved_web_tools(c),[])

    def test_no_reply_is_not_verified(self):
        c=chat('{"url":"https://stockanalysis.com/markets/gainers/"}', [])
        r=audit_saved_web_tools(c)[0]
        self.assertEqual(r["status"],"missing_or_empty_result")

    def test_secret_query_not_returned(self):
        c=chat('{"url":"https://stockanalysis.com/markets/gainers/?apikey=PRIVATE"}',
               [{"type":"input_text","text":"Ticker table"}])
        self.assertNotIn("PRIVATE",str(audit_saved_web_tools(c)))
        self.assertEqual(audit_saved_web_tools(c)[0]["source_path"],"/markets/gainers/")

    def test_search_web_does_not_fake_fetch_url(self):
        c=chat('{"query":"top gainers"}',
               [{"type":"input_text","text":"search results"}], name="search_web")
        r=audit_saved_web_tools(c)[0]
        self.assertIsNone(r["source_host"])
        self.assertEqual(r["tool"],"search_web")

    def test_invalid_saved_chat_rejected(self):
        with self.assertRaises(ValueError):
            audit_saved_web_tools([])

    def test_provider_time_never_inferred_from_model_reply(self):
        c=chat('{"url":"https://stockanalysis.com/markets/gainers/"}',
               [{"type":"input_text","text":"BOLT up 69 percent"}])
        self.assertIsNone(audit_saved_web_tools(c)[0]["retrieved_at_source_utc"])


if __name__=="__main__":
    unittest.main()

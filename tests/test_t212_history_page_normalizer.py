"""Synthetic contract for the real WebUI T212 recent_order_history page layout.

No brokerage/network calls or credentials. Saved history remains unverified.
"""
import json
import unittest
from runtime.deepseek.t212_history_page_normalizer import normalise_saved_history,safe_summary,decode_saved_response

ORDER={"id":1234,"status":"FILLED","ticker":"MYGN","side":"BUY","currency":"USD",
       "filledQuantity":3.0,"instrument":{"ticker":"MYGN","currency":"USD"}}
FILL={"id":777,"quantity":3.0,"price":5.56,"filledAt":"2026-10-22T15:35:25Z"}
PAGE={"items":[{"order":ORDER,"fill":FILL}],"nextPagePath":None}

class HistoryPageTests(unittest.TestCase):
    def test_webui_text_output_unwrapped(self):
        stored=[{"type":"text","text":json.dumps(PAGE)}]
        self.assertEqual(decode_saved_response(stored)["items"][0]["order"]["id"],1234)
        self.assertEqual(len(normalise_saved_history(stored)["candidates"]),1)
    def test_fill_id_retained_not_order_confused(self):
        r=normalise_saved_history(PAGE)["candidates"][0]
        self.assertEqual(r["brokerOrderId"],"1234")
        self.assertEqual(r["brokerFillId"],"777")
        self.assertEqual(r["currency"],"USD")
        self.assertFalse(r["broker_verified"])
        self.assertEqual(r["source"],"SAVED_WEBUI_T212_HISTORY_UNCONFIRMED")
    def test_safe_summary_redacts_identity_and_price(self):
        s=json.dumps(safe_summary(normalise_saved_history(PAGE)))
        for token in ("1234","777","MYGN","5.56"):self.assertNotIn(token,s)
    def test_cancelled_is_not_filled(self):
        page={"items":[{"order":{**ORDER,"status":"CANCELLED"},"fill":FILL}]}
        self.assertEqual(normalise_saved_history(page)["candidates"],[])
    def test_repeated_identical_fill_idempotent(self):
        self.assertEqual(len(normalise_saved_history({"items":PAGE["items"]*2})["candidates"]),1)
    def test_multiple_fills_quarantined(self):
        other={"order":ORDER,"fill":{**FILL,"id":778,"quantity":1.0}}
        r=normalise_saved_history({"items":[PAGE["items"][0],other]})
        self.assertEqual(r["candidates"],[])
        self.assertEqual(r["quarantined_items"],2)
    def test_changed_duplicate_quarantined(self):
        other={"order":ORDER,"fill":{**FILL,"price":5.57}}
        r=normalise_saved_history({"items":[PAGE["items"][0],other]})
        self.assertEqual(len(r["candidates"]),0)
    def test_partial_quantity_quarantined(self):
        page={"items":[{"order":ORDER,"fill":{**FILL,"quantity":2.0}}]}
        self.assertEqual(normalise_saved_history(page)["candidates"],[])
    def test_currency_conflict_quarantined(self):
        page={"items":[{"order":{**ORDER,"instrument":{"ticker":"MYGN","currency":"GBP"}},"fill":FILL}]}
        self.assertEqual(normalise_saved_history(page)["candidates"],[])
    def test_missing_timezone_quarantined(self):
        page={"items":[{"order":ORDER,"fill":{**FILL,"filledAt":"2026-10-22T15:35:25"}}]}
        self.assertEqual(normalise_saved_history(page)["candidates"],[])
    def test_nonpositive_price_quarantined(self):
        page={"items":[{"order":ORDER,"fill":{**FILL,"price":-1}}]}
        self.assertEqual(normalise_saved_history(page)["candidates"],[])
    def test_pagination_marker_visible(self):
        self.assertTrue(normalise_saved_history({**PAGE,"nextPagePath":"/next"})["page_has_next"])
    def test_bad_shape_rejected(self):
        with self.assertRaises(ValueError):normalise_saved_history({"orders":[]})
    def test_bounded_page(self):
        with self.assertRaises(ValueError):normalise_saved_history({"items":[{}]*501})
    def test_unverified_cannot_be_canonical_finmem_fill(self):
        from runtime.deepseek.t212_history_page_normalizer import normalise_saved_history
        r=normalise_saved_history(PAGE)["candidates"][0]
        self.assertNotEqual(r["source"],"T212_DEMO_RECENT_ORDER_HISTORY")
        self.assertIsNone(r["realisedPnL"])
    def test_independent_broker_verification_not_claimed(self):
        r=normalise_saved_history(PAGE)
        self.assertFalse(r["broker_verified"])
        self.assertEqual(r["finmem_outcomes_written"],0)
        self.assertEqual(r["orders_placed"],0)
if __name__=="__main__":unittest.main()

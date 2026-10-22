"""Offline-only T212 saved-vs-fresh receipt reconciliation tests."""
import unittest
from runtime.deepseek.t212_history_page_normalizer import normalise_saved_history
from runtime.deepseek.t212_history_reconciliation import reconcile_saved_against_fresh

ORDER={"id":912345,"ticker":"MYGN","instrument":{"ticker":"MYGN","currency":"USD"},
 "currency":"USD","side":"BUY","status":"FILLED","filledQuantity":2.0}
FILL={"id":202,"quantity":2.0,"price":5.55,"filledAt":"2026-10-21T14:00:00Z"}
PAGE={"items":[{"order":ORDER,"fill":FILL}],"nextPagePath":None}
CHECK="2026-10-22T21:00:00Z"

class BrokerReconciliation(unittest.TestCase):
    def setUp(self):self.saved=normalise_saved_history(PAGE)["candidates"][0]
    def reconcile(self, fresh=PAGE, **kw):
        return reconcile_saved_against_fresh(
            self.saved,fresh,fresh_authenticated_demo_call=kw.get("authenticated",True),
            attested_at_utc=kw.get("at",CHECK))
    def test_matching_order_and_fill_generates_candidate(self):
        x=self.reconcile()
        self.assertEqual(x["brokerOrderId"],"912345")
        self.assertEqual(x["brokerFillId"],"202")
        self.assertEqual(x["source"],"T212_DEMO_RECENT_ORDER_HISTORY")
        self.assertIsNone(x["realisedPnL"])
        self.assertFalse(x["research_decision_linked"])
        self.assertEqual(len(x["reconciliation_sha256"]),64)
    def test_not_authorised_rejected(self):
        with self.assertRaisesRegex(ValueError,"authenticated"):self.reconcile(authenticated=False)
    def test_missing_order_rejected(self):
        with self.assertRaises(ValueError):self.reconcile({"items":[]})
    def test_conflicting_price_rejected(self):
        with self.assertRaisesRegex(ValueError,"differs"):
            self.reconcile({"items":[{"order":ORDER,"fill":{**FILL,"price":5.56}}]})
    def test_conflicting_fill_id_rejected(self):
        with self.assertRaisesRegex(ValueError,"differs"):
            self.reconcile({"items":[{"order":ORDER,"fill":{**FILL,"id":203}}]})
    def test_conflicting_currency_rejected(self):
        with self.assertRaises(ValueError):
            changed={**ORDER,"currency":"GBP","instrument":{"ticker":"MYGN","currency":"GBP"}}
            self.reconcile({"items":[{"order":changed,"fill":FILL}]})
    def test_cancelled_not_filled(self):
        with self.assertRaises(ValueError):
            self.reconcile({"items":[{"order":{**ORDER,"status":"CANCELLED"},"fill":FILL}]})
    def test_reject_model_prose(self):
        with self.assertRaises(ValueError):
            reconcile_saved_against_fresh({"content":"I bought shares"},PAGE,
                fresh_authenticated_demo_call=True,attested_at_utc=CHECK)
    def test_fresh_call_timestamp_cannot_precede_fill(self):
        with self.assertRaisesRegex(ValueError,"future"):
            self.reconcile(at="2026-10-20T00:00:00Z")
    def test_timestamp_must_be_timezone_aware(self):
        with self.assertRaises(ValueError):
            self.reconcile(at="2026-10-22T21:00:00")
    def test_multi_fill_group_quarantined(self):
        many={"items":[{"order":ORDER,"fill":FILL},
          {"order":ORDER,"fill":{**FILL,"id":204,"quantity":1.0}}]}
        with self.assertRaises(ValueError):self.reconcile(many)
    def test_no_research_or_trade_writes(self):
        x=self.reconcile()
        self.assertNotIn("order_instruction",x)
        self.assertNotIn("research_outcome",x)
if __name__=="__main__":unittest.main()

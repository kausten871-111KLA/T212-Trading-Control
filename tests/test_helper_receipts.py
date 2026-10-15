import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from helper_receipts import extract_receipts


def fixture(payload='[]',name='list_positions'):
    return [{'type':'function_call','call_id':'c','name':name},
            {'type':'function_call_output','call_id':'c','status':'completed',
             'output':[{'type':'input_text','text':payload}]}]


class ReceiptsTests(unittest.TestCase):
    def test_reasoning_and_prose_never_evidence(self):
        self.assertEqual(extract_receipts([{'type':'reasoning','content':'all orders filled'},{'type':'message','content':'broker verified'}]),[])
    def test_completed_transport_with_error_not_pass(self):
        r=extract_receipts(fixture('{"error":"429"}'))
        self.assertEqual(r[0]['status'],'ERROR_OR_INVALID_PAYLOAD')
    def test_empty_positions_is_valid_but_not_current(self):
        r=extract_receipts(fixture())[0]
        self.assertEqual(r['summary'],{'result_count':0});self.assertFalse(r['fresh_broker_check'])
    def test_malformed_json(self):
        self.assertEqual(extract_receipts(fixture('not json'))[0]['status'],'ERROR_OR_INVALID_PAYLOAD')
    def test_orphan_and_duplicate_receipts_fail(self):
        for data in [fixture()[1:],fixture()+fixture()[1:]]:
            with self.assertRaises(ValueError):extract_receipts(data)
    def test_missing_output_explicit(self):
        self.assertEqual(extract_receipts(fixture()[:1])[0]['status'],'MISSING_OUTPUT')
    def test_account_identifiers_not_exported(self):
        payload='{"environment":"DEMO","liveTradingEnabled":false,"openPositionCount":0,"pendingOrderCount":0,"account":{"id":"secret-account","cash":123}}'
        r=extract_receipts(fixture(payload,'trading_dashboard'))[0]
        self.assertNotIn('secret-account',str(r));self.assertNotIn('cash',str(r))
    def test_history_pagination_disclosed(self):
        r=extract_receipts(fixture('{"items":[],"nextPagePath":"/page2"}','recent_order_history'))[0]
        self.assertTrue(r['summary']['pagination_present'])
    def test_wrong_payload_shape_is_invalid(self):
        self.assertEqual(extract_receipts(fixture('{}'))[0]['status'],'ERROR_OR_INVALID_PAYLOAD')

if __name__=='__main__':unittest.main()

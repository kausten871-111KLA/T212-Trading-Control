import concurrent.futures
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from runtime.deepseek.orchestrator import StateDB, Orchestrator

class RuntimeQueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=str(Path(self.tmp.name)/'state.sqlite')
        self.db=StateDB(self.path);self.addCleanup(self.db.conn.close);self.db.init_schema()
    def test_twenty_tables_preserved(self):
        self.assertEqual(len(self.db.conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()),20)
    def test_routing(self):
        scout=self.db.emit('PREMARKET_INGEST',{});execute=self.db.emit('EXECUTE_ORDER',{})
        self.db.emit('MARKET_OPEN',{})
        self.assertEqual([r['id'] for r in self.db.claim('executor',('EXECUTE_ORDER',))],[execute])
        self.assertEqual([r['id'] for r in self.db.claim('scout',('PREMARKET_INGEST',))],[scout])
        self.assertEqual(self.db.conn.execute("SELECT status FROM event_queue WHERE event_type='MARKET_OPEN'").fetchone()[0],'pending')
    def test_two_connections_claim_once(self):
        self.db.emit('EXECUTE_ORDER',{})
        other=StateDB(self.path);self.addCleanup(other.conn.close)
        barrier=threading.Barrier(2)
        def claim(db,worker):
            barrier.wait();return db.claim(worker,('EXECUTE_ORDER',))
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            a=pool.submit(claim,self.db,'a');b=pool.submit(claim,other,'b')
            self.assertEqual(len(a.result())+len(b.result()),1)
    def test_shared_connection_threads(self):
        with concurrent.futures.ThreadPoolExecutor(4) as pool:
            ids=list(pool.map(lambda n:self.db.emit('CANDIDATE_FOUND',{'n':n}),range(40)))
        self.assertEqual(len(set(ids)),40)
    def test_wrong_owner(self):
        self.db.emit('EXECUTE_ORDER',{});ev=self.db.claim('a',('EXECUTE_ORDER',))[0]
        self.assertFalse(self.db.complete(ev['id'],'b',ev['claim_token']))
        self.assertFalse(self.db.fail(ev['id'],'b',ev['claim_token'],'wrong'))
        self.assertTrue(self.db.complete(ev['id'],'a',ev['claim_token']))
    def test_expiry_and_same_worker_old_token(self):
        self.db.emit('EXECUTE_ORDER',{});old=self.db.claim('a',('EXECUTE_ORDER',))[0]
        self.db.conn.execute('UPDATE event_queue SET lease_expires_at=0');self.db.conn.commit()
        self.assertFalse(self.db.complete(old['id'],'a',old['claim_token']))
        self.assertEqual(self.db.requeue_dead(('EXECUTE_ORDER',)),1)
        new=self.db.claim('a',('EXECUTE_ORDER',))[0]
        self.assertNotEqual(old['claim_token'],new['claim_token'])
        self.assertFalse(self.db.fail(old['id'],'a',old['claim_token'],'stale'))
        self.assertFalse(self.db.complete(old['id'],'a',old['claim_token']))
        self.assertTrue(self.db.complete(new['id'],'a',new['claim_token']))
    def test_attempt_budget(self):
        event=self.db.emit('EXECUTE_ORDER',{})
        self.db.conn.execute('UPDATE event_queue SET max_attempts=1 WHERE id=?',(event,));self.db.conn.commit()
        ev=self.db.claim('a',('EXECUTE_ORDER',))[0]
        self.assertTrue(self.db.fail(event,'a',ev['claim_token'],'synthetic'))
        self.assertEqual(self.db.conn.execute('SELECT status FROM event_queue').fetchone()[0],'failed')
    def test_init_preserves_data(self):
        event=self.db.emit('MARKET_OPEN',{'source':'existing'});self.db.init_schema()
        self.assertEqual(self.db.conn.execute('SELECT id FROM event_queue').fetchone()[0],event)
    def test_no_scheduler(self):
        runtime=Orchestrator(self.db,None,None);runtime.stop_event.set()
        with patch('runtime.deepseek.orchestrator.threading.Thread') as thread:runtime.run()
        self.assertEqual([c.kwargs['args'][2] for c in thread.call_args_list],[('PREMARKET_INGEST',),('EXECUTE_ORDER',)])
        import inspect
        self.assertNotIn('BackgroundScheduler(',inspect.getsource(runtime.run))
    def test_unknown_does_not_invent_broker_id(self):
        self.db.upsert_order(None,'i','ACME','BUY',1,'MARKET','UNKNOWN',{})
        self.assertEqual(self.db.conn.execute('SELECT COUNT(*) FROM "order"').fetchone()[0],0)
        self.assertEqual(self.db.conn.execute('SELECT COUNT(*) FROM recovery_record').fetchone()[0],1)
    def test_duplicate_executor_event_reconciles_without_resubmission(self):
        from runtime.deepseek.orchestrator import OrderResult
        from unittest.mock import Mock
        import json
        gateway=Mock()
        gateway.place_market.return_value=OrderResult(None,'i','UNKNOWN')
        gateway.reconcile.return_value={'status':'UNKNOWN','receipt':{}}
        runtime=Orchestrator(self.db,gateway,None)
        event=self.db.emit('EXECUTE_ORDER',{})
        ev={'id':event,'payload':json.dumps({'intent_id':'i','ticker':'ACME','side':'BUY','quantity':1})}
        self.assertFalse(runtime.handle_executor(ev))
        self.assertFalse(runtime.handle_executor(ev))
        gateway.place_market.assert_called_once()
        gateway.reconcile.assert_called_once_with('i')
    def test_intent_conflict_rejected(self):
        p={'intent_id':'i','ticker':'ACME','side':'BUY','quantity':1}
        self.assertTrue(self.db.prepare_intent(p))
        with self.assertRaises(ValueError):self.db.prepare_intent(dict(p,quantity=2))

import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from runtime.deepseek.controller_phase_bridge import ControllerPhaseBridge, PHASE_BY_AUTOMATION
from runtime.deepseek.controller_dispatch import ControllerPhaseDispatcher
from runtime.deepseek.controller_ack import ControllerAcknowledgements

OPEN = next(iter(PHASE_BY_AUTOMATION))

class DB:
    def __init__(self, path):
        self.lock=threading.RLock()
        self.conn=sqlite3.connect(path,check_same_thread=False)
        self.conn.row_factory=sqlite3.Row
        self.conn.execute('PRAGMA busy_timeout=5000')
        self.conn.execute('PRAGMA journal_mode=WAL')
        self.conn.execute('PRAGMA foreign_keys=ON')
        self.conn.executescript(Path('runtime/deepseek/schema.sql').read_text())
        self.conn.execute('ALTER TABLE event_queue ADD COLUMN claim_token TEXT')
        self.conn.commit()

class AckTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.db=DB(str(Path(self.tmp.name)/'state.db')); self.addCleanup(self.db.conn.close)
        auth=lambda p,a:p=='host' and a in PHASE_BY_AUTOMATION
        self.bridge=ControllerPhaseBridge(self.db,auth)
        self.dispatch=ControllerPhaseDispatcher(self.db); self.dispatch.install_schema()
        self.acks=ControllerAcknowledgements(self.db,auth); self.acks.install_schema()
        eid,_=self.bridge.enqueue(automation_id=OPEN,market_date='2026-10-19',principal='host')
        self.db.conn.execute("UPDATE event_queue SET status='claimed',worker_id='worker',claim_token='claim',lease_expires_at=9999999999 WHERE id=?",(eid,));self.db.conn.commit()
        self.instruction,_=self.dispatch.dispatch_claim({'id':eid,'worker_id':'worker','claim_token':'claim'})
        self.event=eid

    def ack(self,outcome=None,principal='host'):
        return self.acks.acknowledge(instruction_id=self.instruction,principal=principal,
                                     outcome=outcome or {'processing':'completed','decision_ref':'d-1'})

    def test_ack_persists_and_links_dispatch(self):
        rid,created=self.ack();self.assertTrue(created)
        self.assertEqual(self.acks.status(instruction_id=self.instruction,principal='host')['receipt_id'],rid)
        self.assertEqual(self.db.conn.execute('SELECT event_id FROM controller_result WHERE id=?',(rid,)).fetchone()[0],self.event)
        self.assertEqual(self.db.conn.execute('SELECT status FROM controller_instruction WHERE id=?',(self.instruction,)).fetchone()[0],'acknowledged')

    def test_replay_same_payload_returns_existing(self):
        first=self.ack(); second=self.ack();self.assertEqual(second,(first[0],False))
        self.assertEqual(self.db.conn.execute("SELECT count(*) FROM controller_result WHERE kind='CONTROLLER_ACK'").fetchone()[0],1)

    def test_conflicting_outcome_rejected(self):
        self.ack()
        with self.assertRaisesRegex(ValueError,'Conflicting'):self.ack({'processing':'failed'})

    def test_unauthorized_principal_rejected(self):
        with self.assertRaises(PermissionError):self.ack(principal='stranger')
        with self.assertRaises(PermissionError):self.acks.status(instruction_id=self.instruction,principal='stranger')
        self.assertEqual(self.db.conn.execute("SELECT count(*) FROM controller_result WHERE kind='CONTROLLER_ACK'").fetchone()[0],0)

    def test_invalid_json_numeric_rejected(self):
        with self.assertRaises(ValueError):self.ack({'bad':float('nan')})
        self.assertEqual(self.db.conn.execute("SELECT count(*) FROM controller_result WHERE kind='CONTROLLER_ACK'").fetchone()[0],0)

    def test_no_migration_fails_closed(self):
        self.db.conn.execute('DROP INDEX idx_controller_ack_once');self.db.conn.commit()
        with self.assertRaises(RuntimeError):self.ack()
        self.assertEqual(self.db.conn.execute('SELECT status FROM controller_instruction WHERE id=?',(self.instruction,)).fetchone()[0],'issued')

    def test_receipt_write_failure_rolls_back_status(self):
        self.db.conn.execute("CREATE TRIGGER fail_ack BEFORE INSERT ON controller_result WHEN NEW.kind='CONTROLLER_ACK' BEGIN SELECT RAISE(FAIL,'failure'); END")
        self.db.conn.commit()
        with self.assertRaises(sqlite3.IntegrityError):self.ack()
        self.assertEqual(self.db.conn.execute('SELECT status FROM controller_instruction WHERE id=?',(self.instruction,)).fetchone()[0],'issued')

    def test_broken_event_link_rejected(self):
        self.db.conn.execute('DELETE FROM controller_result WHERE kind=\'PHASE_DISPATCH\'');self.db.conn.commit()
        with self.assertRaisesRegex(ValueError,'linkage'):self.ack()

    def test_status_before_ack(self):
        self.assertEqual(self.acks.status(instruction_id=self.instruction,principal='host'),
                         {'instruction_id':self.instruction,'status':'issued','receipt_id':None,'outcome':None})

    def test_concurrent_ack_single_receipt(self):
        results=[]; errors=[]
        def worker():
            try:results.append(self.ack())
            except Exception as exc:errors.append(exc)
        threads=[threading.Thread(target=worker) for _ in range(8)]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertEqual(errors,[])
        self.assertEqual(sum(created for _,created in results),1)
        self.assertEqual(len({rid for rid,_ in results}),1)

    def test_no_new_tables(self):
        n=self.db.conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchone()[0]
        self.assertEqual(n,20)

    def test_restart_persists_ack_and_prevents_duplicate(self):
        receipt,_=self.ack()
        # Simulate a new host process opening the existing WAL database.
        db2=type('DB2', (), {})()
        db2.lock=threading.RLock()
        db2.conn=sqlite3.connect(self.db.conn.execute('PRAGMA database_list').fetchone()[2],check_same_thread=False)
        db2.conn.row_factory=sqlite3.Row
        self.addCleanup(db2.conn.close)
        resumed=ControllerAcknowledgements(db2,lambda p,a:p=='host')
        self.assertEqual(resumed.acknowledge(instruction_id=self.instruction,principal='host',
                           outcome={'decision_ref':'d-1','processing':'completed'}),(receipt,False))
        self.assertEqual(resumed.status(instruction_id=self.instruction,principal='host')['status'],'acknowledged')

    def test_unique_index_rejects_duplicate_ack_rows(self):
        receipt,_=self.ack()
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.conn.execute("INSERT INTO controller_result(controller_instruction_id,event_id,kind,payload,created_at) "
                "VALUES(?,?,'CONTROLLER_ACK','{}',0)",(self.instruction,self.event))
        self.db.conn.rollback()

    def test_wrong_instruction_type_rejected(self):
        self.db.conn.execute("UPDATE controller_instruction SET instruction_type='EXECUTE_ORDER' WHERE id=?",(self.instruction,));self.db.conn.commit()
        with self.assertRaisesRegex(ValueError,'Unknown phase'):self.ack()

if __name__=='__main__':unittest.main()

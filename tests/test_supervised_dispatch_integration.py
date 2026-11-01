import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from runtime.deepseek.controller_phase_bridge import ControllerPhaseBridge, PHASE_BY_AUTOMATION
from runtime.deepseek.controller_dispatch import ControllerPhaseDispatcher
from runtime.deepseek.worker_supervisor import WorkerSupervisor

SCHEMA=Path(__file__).resolve().parents[1]/'runtime/deepseek/schema.sql'
class DB:
    def __init__(self,path):
        self.lock=threading.RLock();self.conn=sqlite3.connect(path,check_same_thread=False)
        self.conn.row_factory=sqlite3.Row
        self.conn.executescript(SCHEMA.read_text())
        self.conn.execute('ALTER TABLE event_queue ADD COLUMN claim_token TEXT')
        self.conn.commit()

class SupervisedDispatchTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.db=DB(str(Path(temp.name)/'state.sqlite'));self.addCleanup(self.db.conn.close)
        self.supervisor=WorkerSupervisor(self.db);self.supervisor.install_schema()
        self.dispatcher=ControllerPhaseDispatcher(self.db,supervisor=self.supervisor)
        self.dispatcher.install_schema()
        self.bridge=ControllerPhaseBridge(self.db,lambda p,a:p=='host')
        self.automation=next(iter(PHASE_BY_AUTOMATION))
        self.event,_=self.bridge.enqueue(automation_id=self.automation,market_date='2026-10-19',principal='host')

    def claim(self,worker,token='event-token'):
        self.db.conn.execute("UPDATE event_queue SET status='claimed',worker_id=?,claim_token=?,lease_expires_at=9999999999 WHERE id=?",(worker,token,self.event))
        self.db.conn.commit()
        return {'id':self.event,'worker_id':worker,'claim_token':token}

    def test_current_worker_dispatches_once(self):
        worker=self.supervisor.acquire('controller',ttl=300,now=100)
        self.db.conn.execute('UPDATE worker SET lease_expires_at=9999999999 WHERE id=?',(worker,));self.db.conn.commit()
        event=self.claim(worker)
        self.assertTrue(self.dispatcher.dispatch_claim(event)[1])
        self.assertIsNone(self.dispatcher.dispatch_claim(event))
        self.assertEqual(self.db.conn.execute('SELECT count(*) FROM controller_instruction').fetchone()[0],1)

    def test_stale_worker_cannot_dispatch_even_with_valid_event_claim(self):
        old=self.supervisor.acquire('controller',ttl=10,now=100)
        new=self.supervisor.acquire('controller',ttl=10,now=111)
        self.db.conn.execute('UPDATE worker SET lease_expires_at=9999999999 WHERE id=?',(new,));self.db.conn.commit()
        event=self.claim(old)
        self.assertIsNone(self.dispatcher.dispatch_claim(event))
        self.assertEqual(self.db.conn.execute('SELECT count(*) FROM controller_instruction').fetchone()[0],0)
        self.assertEqual(self.db.conn.execute('SELECT status FROM event_queue').fetchone()[0],'claimed')

    def test_noncontroller_role_cannot_dispatch(self):
        worker=self.supervisor.acquire('executor',ttl=10,now=100)
        self.db.conn.execute('UPDATE worker SET lease_expires_at=9999999999 WHERE id=?',(worker,));self.db.conn.commit()
        self.assertIsNone(self.dispatcher.dispatch_claim(self.claim(worker)))
        self.assertEqual(self.db.conn.execute('SELECT count(*) FROM controller_instruction').fetchone()[0],0)

if __name__=='__main__':unittest.main()

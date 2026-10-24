"""Focused offline acceptance against the exact PR17 schema blob."""
import concurrent.futures
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from runtime.deepseek.worker_supervisor import WorkerSupervisor

SCHEMA = Path(__file__).resolve().parents[1] / 'runtime/deepseek/schema.sql'

class DB:
    def __init__(self, path):
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('PRAGMA busy_timeout=5000')
        self.conn.execute('PRAGMA journal_mode=WAL')
        self.conn.executescript(SCHEMA.read_text())
        self.conn.commit()

class WorkerLeaseTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.path = str(Path(tmp.name)/'state.sqlite')
        self.db = DB(self.path); self.addCleanup(self.db.conn.close)
        self.s = WorkerSupervisor(self.db); self.s.install_schema()

    def test_acquire_and_reject_second_owner(self):
        a=self.s.acquire('controller',now=100,ttl=20)
        self.assertTrue(a)
        self.assertIsNone(self.s.acquire('controller',now=101))
        self.assertTrue(self.s.owns(a,now=101))

    def test_expiry_takeover_fences_old_token(self):
        a=self.s.acquire('executor',now=100,ttl=10)
        b=self.s.acquire('executor',now=111,ttl=10)
        self.assertNotEqual(a,b)
        self.assertFalse(self.s.heartbeat(a,now=112))
        self.assertFalse(self.s.release(a,now=112))
        self.assertTrue(self.s.owns(b,now=112))

    def test_heartbeat_extends_and_prevents_takeover(self):
        a=self.s.acquire('monitor',now=100,ttl=10)
        self.assertTrue(self.s.heartbeat(a,now=105,ttl=20))
        self.assertIsNone(self.s.acquire('monitor',now=115))
        self.assertTrue(self.s.owns(a,now=124))
        self.assertFalse(self.s.owns(a,now=125))

    def test_release_frees_role(self):
        a=self.s.acquire('scout',now=100)
        self.assertTrue(self.s.release(a,now=110))
        self.assertFalse(self.s.release(a,now=111))
        self.assertTrue(self.s.acquire('scout',now=111))

    def test_independent_roles(self):
        self.assertTrue(self.s.acquire('controller',now=100))
        self.assertTrue(self.s.acquire('executor',now=100))

    def test_restart_persists_ownership(self):
        a=self.s.acquire('controller',now=100,ttl=20)
        other=DB(self.path);self.addCleanup(other.conn.close)
        s2=WorkerSupervisor(other)
        self.assertIsNone(s2.acquire('controller',now=101))
        self.assertTrue(s2.heartbeat(a,now=101))

    def test_two_sqlite_connections_compete_once(self):
        other=DB(self.path);self.addCleanup(other.conn.close)
        s2=WorkerSupervisor(other)
        barrier=threading.Barrier(2)
        def claim(s):
            barrier.wait()
            return s.acquire('controller',now=100)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            a=pool.submit(claim,self.s);b=pool.submit(claim,s2)
            results=[a.result(),b.result()]
        self.assertEqual(sum(x is not None for x in results),1)

    def test_reinstall_does_not_add_tables(self):
        before=self.db.conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchone()[0]
        self.s.install_schema()
        after=self.db.conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchone()[0]
        self.assertEqual((before,after),(20,20))

    def test_missing_index_blocks_acquire(self):
        self.db.conn.execute('DROP INDEX idx_worker_one_active_role');self.db.conn.commit()
        with self.assertRaises(RuntimeError):self.s.acquire('controller',now=100)
        self.assertEqual(self.db.conn.execute('SELECT count(*) FROM worker').fetchone()[0],0)

    def test_historical_duplicate_active_roles_block_migration(self):
        self.db.conn.execute('DROP INDEX idx_worker_one_active_role')
        self.db.conn.execute("INSERT INTO worker(id,role,status) VALUES('a','controller','active'),('b','controller','active')")
        self.db.conn.commit()
        with self.assertRaises(sqlite3.IntegrityError):self.s.install_schema()
        self.assertEqual(self.db.conn.execute('SELECT count(*) FROM worker').fetchone()[0],2)

    def test_invalid_lease_inputs(self):
        for bad in (0,-1,float('nan'),float('inf'),True):
            with self.assertRaises(ValueError):self.s.acquire('controller',ttl=bad,now=100)
        with self.assertRaises(ValueError):self.s.acquire('',now=100)
        with self.assertRaises(ValueError):self.s.acquire('controller',now=float('nan'))

    def test_status_does_not_claim_expired_worker(self):
        a=self.s.acquire('controller',now=100,ttl=10)
        self.assertFalse(self.s.status('controller',now=110)[0]['currently_owned'])
        self.assertTrue(self.s.status('controller',now=109)[0]['currently_owned'])

    def test_no_schedules_or_broker_connections(self):
        self.s.acquire('controller',now=100)
        self.assertEqual(self.db.conn.execute('SELECT count(*) FROM event_queue').fetchone()[0],0)
        self.assertEqual(self.db.conn.execute('SELECT count(*) FROM "order"').fetchone()[0],0)

if __name__=='__main__': unittest.main()

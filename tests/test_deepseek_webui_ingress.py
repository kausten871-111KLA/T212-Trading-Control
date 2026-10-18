import datetime
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from runtime.deepseek.service import migrate
from runtime.deepseek.orchestrator import StateDB
from runtime.deepseek.webui_ingress import WebUIAutomationIngress, MODEL_ID
from runtime.deepseek.controller_phase_bridge import PHASE_BY_AUTOMATION

class IngressTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); path=Path(self.tmp.name)/'state.db'; migrate(path)
        self.db=StateDB(str(path)); self.aid=next(iter(PHASE_BY_AUTOMATION))
        self.user=SimpleNamespace(id='owner')
        self.automation=SimpleNamespace(id=self.aid,user_id='owner',data={'model_id':MODEL_ID})
        self.allowed=True
        async def load(aid): return self.automation
        async def permitted(user): return self.allowed
        self.hook=WebUIAutomationIngress(self.db,load_automation=load,owner_permitted=permitted)
        self.at=datetime.datetime(2026,10,20,0,30,tzinfo=datetime.timezone.utc)
    def tearDown(self): self.db.conn.close();self.tmp.cleanup()
    async def call(self):
        return await self.hook.enqueue(automation_id=self.aid,authenticated_user=self.user,scheduled_at=self.at)
    async def test_replayed_occurrence_dedupes_using_market_date(self):
        eid,created=await self.call(); self.assertTrue(created)
        self.assertEqual(await self.call(),(eid,False))
        row=self.db.conn.execute('SELECT correlation_id FROM event_queue').fetchone()
        self.assertTrue(row[0].endswith('2026-10-19'))
    async def test_revoked_owner_rejected(self):
        self.allowed=False
        with self.assertRaises(PermissionError): await self.call()
    async def test_other_owner_rejected(self):
        self.user=SimpleNamespace(id='other')
        with self.assertRaises(PermissionError): await self.call()
    async def test_changed_model_rejected(self):
        self.automation.data['model_id']='other'
        with self.assertRaises(PermissionError): await self.call()
    async def test_naive_time_rejected(self):
        self.at=self.at.replace(tzinfo=None)
        with self.assertRaises(ValueError): await self.call()

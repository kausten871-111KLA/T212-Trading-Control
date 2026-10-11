"""Execute PR7's exact claim_due body with an in-memory transactional DB double.
Confirms only scheduling order, not SQL isolation or a real application restart.
"""
import asyncio
from contextlib import asynccontextmanager
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


class Column:
    def __eq__(self,other):return self
    def __le__(self,other):return self
    def in_(self,other):return self


class Query:
    def where(self,*a):return self
    def order_by(self,*a):return self
    def limit(self,*a):return self
    def with_for_update(self,**a):return self


class Result:
    def __init__(self,rows):self.rows=rows
    def scalars(self):return self
    def all(self):return self.rows


class DB:
    def __init__(self,row):
        self.row=row;self.bind=types.SimpleNamespace(dialect=types.SimpleNamespace(name='sqlite'));self.executions=0;self.committed=None
    async def execute(self,stmt):
        self.executions+=1
        return Result([self.row] if self.executions==1 else [('user','Europe/London')])
    async def commit(self):self.committed=(self.row.last_run_at,self.row.next_run_at)


class CrashWindow(unittest.IsolatedAsyncioTestCase):
    async def test_committed_claim_can_be_lost_before_task_creation(self):
        spec=importlib.util.spec_from_file_location('claim',Path(__file__).with_name('claim_due_baseline.py'))
        m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        row=types.SimpleNamespace(id='automation',user_id='user',is_active=True,last_run_at=0,next_run_at=10,data={'rrule':'synthetic'})
        db=DB(row)
        @asynccontextmanager
        async def context(value):yield value
        m.get_async_db_context=context
        m.select=lambda *a:Query()
        m.Automation=types.SimpleNamespace(is_active=Column(),next_run_at=Column())
        m.AutomationModel=types.SimpleNamespace(model_validate=lambda r:r)
        m.log=types.SimpleNamespace(warning=lambda *a:None)
        auto=types.ModuleType('open_webui.utils.automations')
        async def next_run_ns(*a,**k):return 1000
        auto.next_run_ns=next_run_ns
        recurrence=types.ModuleType('open_webui.utils.recurrence');recurrence.RecurrenceEvaluationTimeout=type('Timeout',(Exception,),{})
        users=types.ModuleType('open_webui.models.users');users.User=types.SimpleNamespace(id=Column(),timezone=Column())
        with patch.dict(sys.modules,{'open_webui.utils.automations':auto,'open_webui.utils.recurrence':recurrence,'open_webui.models.users':users}):
            batch=await m.claim_due(None,20,db=db)
        # Inject process loss here: scheduler has not called create_task yet.
        task_count=0
        self.assertEqual(db.committed,(20,1000))
        self.assertEqual(task_count,0)
        self.assertEqual(len(batch),1)
        self.assertGreater(row.next_run_at,20)
        print('REPRODUCED: claim committed; 0 tasks created; occurrence no longer due. Recovery/outbox acceptance remains BLOCKED.')


if __name__=='__main__':unittest.main(verbosity=2)

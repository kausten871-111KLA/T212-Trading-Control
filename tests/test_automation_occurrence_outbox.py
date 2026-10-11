"""Isolated SQLite regression for durable scheduled occurrences.

Mount patched files into an OFFLINE Open WebUI v0.11.4 test container. No
production database, provider call, broker order or WebUI scheduler is started.
"""
import asyncio
import unittest
from contextlib import asynccontextmanager
from unittest.mock import patch, AsyncMock
import types
import sys
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from open_webui.models import automations as mod
from open_webui.models.users import User


class OccurrenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as db:
            await db.run_sync(lambda conn: mod.Base.metadata.create_all(
                conn, tables=[User.__table__, mod.Automation.__table__, mod.AutomationRun.__table__]
            ))
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.Session() as db:
            db.add(User(id='owner-1', name='Owner', timezone='Europe/London'))
            db.add(mod.Automation(
                id='autom-1', user_id='owner-1', name='Synthetic due task',
                data={'prompt':'synthetic', 'model_id':'no-provider', 'rrule':'synthetic'},
                meta={}, is_active=True, last_run_at=None, next_run_at=10,
                created_at=1, updated_at=1,
            ))
            await db.commit()

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def claim(self, now=20, next_due=100):
        @asynccontextmanager
        async def supplied(db):
            yield db
        async with self.Session() as db:
            fake = types.ModuleType('open_webui.utils.automations')
            fake.next_run_ns = AsyncMock(return_value=next_due)
            with patch.object(mod, 'get_async_db_context', supplied), patch.dict(
                sys.modules, {'open_webui.utils.automations': fake}
            ):
                return await mod.Automations.claim_due(now, db=db)

    async def test_outbox_survives_committed_claim_before_task_created(self):
        claimed = await self.claim()
        self.assertEqual(len(claimed), 1)
        # Simulate losing the scheduler process BEFORE asyncio.create_task.
        async with self.Session() as db:
            rows = (await db.execute(select(mod.AutomationRun))).scalars().all()
            task = await db.get(mod.Automation, 'autom-1')
            self.assertEqual(task.next_run_at, 100)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].status, 'pending')
            self.assertEqual(rows[0].id, 'scheduled:autom-1:10')
        @asynccontextmanager
        async def supplied(db):
            yield db
        with patch.object(mod, 'get_async_db_context', supplied):
            async with self.Session() as db:
                batch = await mod.Automations.pending_occurrences(db=db)
            self.assertEqual([(a.id, key) for a, key in batch], [('autom-1', 'scheduled:autom-1:10')])
            async with self.Session() as db:
                self.assertTrue(await mod.Automations.start_occurrence(batch[0][1], db=db))
            async with self.Session() as db:
                self.assertFalse(await mod.Automations.start_occurrence(batch[0][1], db=db))
            async with self.Session() as db:
                self.assertEqual(await mod.Automations.pending_occurrences(db=db), [])
            async with self.Session() as db:
                unresolved = await mod.Automations.unresolved_occurrences(before_ns=21, db=db)
            self.assertEqual(len(unresolved), 1)
            self.assertEqual(unresolved[0].status, 'started')
            # Unknown execution is never automatically re-dispatched.
            async with self.Session() as db:
                self.assertTrue(await mod.AutomationRuns.finish_occurrence(
                    'scheduled:autom-1:10', 'success', chat_id='synthetic-chat', db=db
                ))
            async with self.Session() as db:
                self.assertFalse(await mod.AutomationRuns.finish_occurrence(
                    'scheduled:autom-1:10', 'success', db=db
                ))
                rows = (await db.execute(select(mod.AutomationRun))).scalars().all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].chat_id, 'synthetic-chat')
            self.assertEqual(rows[0].status, 'success')

    async def test_second_claim_does_not_create_duplicate(self):
        await self.claim()
        again = await self.claim(now=20, next_due=101)
        self.assertEqual(again, [])
        async with self.Session() as db:
            self.assertEqual(len((await db.execute(select(mod.AutomationRun))).scalars().all()), 1)

    async def test_retry_after_transaction_rollback_preserves_schedule(self):
        @asynccontextmanager
        async def supplied(db):
            yield db
        async with self.Session() as db:
            async def broken_commit():
                raise RuntimeError('crash before database COMMIT')
            fake = types.ModuleType('open_webui.utils.automations')
            fake.next_run_ns = AsyncMock(return_value=100)
            with patch.object(mod,'get_async_db_context', supplied), patch.dict(
                sys.modules, {'open_webui.utils.automations': fake}
            ), patch.object(db, 'commit', new=broken_commit):
                with self.assertRaisesRegex(RuntimeError, 'crash before database COMMIT'):
                    await mod.Automations.claim_due(20, db=db)
            await db.rollback()
        async with self.Session() as db:
            task = await db.get(mod.Automation, 'autom-1')
            self.assertEqual(task.next_run_at,10)
            self.assertEqual((await db.execute(select(mod.AutomationRun))).scalars().all(), [])

if __name__=='__main__':
    unittest.main()

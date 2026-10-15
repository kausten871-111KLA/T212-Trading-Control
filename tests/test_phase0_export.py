import asyncio
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from publish_phase0_note import export_snapshot,publish,JOBS
from phase0_handoff import MODEL,compile_handoff,render


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.db=Path(self.tmp.name)/'webui.db'
        with sqlite3.connect(self.db) as c:
            c.executescript('create table model(id text,user_id text); create table chat(id text,user_id text,chat text,updated_at integer,created_at integer);create table note(id text,user_id text,title text,data text);')
            c.execute('create table access_grant(resource_type text,resource_id text,principal_type text,principal_id text,permission text)')
            c.execute('insert into model values(?,?)',(MODEL,'owner'))
            for i,aid in enumerate(JOBS):
                chat={'meta':{'automation_id':aid},'models':[MODEL],'history':{'currentId':'a','messages':{'a':{'role':'assistant','content':'result','done':True}}}}
                c.execute('insert into chat values(?,?,?,?,?)',(str(i),'owner',json.dumps(chat),1791984908+i,1791984908+i))

    def test_readonly_export_and_preview_dont_write_note(self):
        result=asyncio.run(publish(str(self.db),'2026-10-14'))
        self.assertEqual(result['result'],'PREVIEW_ONLY')
        self.assertEqual(result['sessions'],['OPEN','MIDDAY','CLOSE'])
        with sqlite3.connect(self.db) as c:self.assertEqual(c.execute('select count(*) from note').fetchone()[0],0)

    def test_current_message_not_arbitrary_last_insert(self):
        with sqlite3.connect(self.db) as c:
            raw=json.loads(c.execute('select chat from chat where id="0"').fetchone()[0])
            raw['history']['messages']['later']={'role':'assistant','content':'unselected branch','done':True}
            c.execute('update chat set chat=? where id="0"',(json.dumps(raw),))
        self.assertEqual(export_snapshot(self.db,'2026-10-14')['runs'][0]['content'],'result')

    def test_mismatched_helper_owner_fails(self):
        with sqlite3.connect(self.db) as c:c.execute('update chat set user_id="other" where id="0"')
        with self.assertRaises(ValueError):export_snapshot(self.db,'2026-10-14')

    def test_existing_match_is_idempotent_without_importing_webui(self):
        content=render(compile_handoff(export_snapshot(self.db,'2026-10-14'),'2026-10-14'))
        with sqlite3.connect(self.db) as c:c.execute('insert into note values(?,?,?,?)',('n','owner','PLAYBOOK — 2026-10-14 — READ_ONLY_SMOKE',json.dumps({'content':{'md':content}})))
        self.assertEqual(asyncio.run(publish(str(self.db),'2026-10-14',True))['result'],'EXISTING_MATCH')

    def test_existing_conflict_preserved(self):
        with sqlite3.connect(self.db) as c:c.execute('insert into note values(?,?,?,?)',('n','owner','PLAYBOOK — 2026-10-14 — READ_ONLY_SMOKE',json.dumps({'content':{'md':'user changes'}})))
        with self.assertRaises(ValueError):asyncio.run(publish(str(self.db),'2026-10-14',True))
        with sqlite3.connect(self.db) as c:self.assertIn('user changes',c.execute('select data from note').fetchone()[0])

    def add_matching_note(self):
        content=render(compile_handoff(export_snapshot(self.db,'2026-10-14'),'2026-10-14'))
        with sqlite3.connect(self.db) as c:
            c.execute('insert into note values(?,?,?,?)',('n','owner','PLAYBOOK — 2026-10-14 — READ_ONLY_SMOKE',json.dumps({'content':{'md':content}})))

    def test_shared_existing_note_rejected_without_mutation(self):
        self.add_matching_note()
        for principal in ('user','group','public'):
            with self.subTest(principal=principal):
                with sqlite3.connect(self.db) as c:
                    c.execute('delete from access_grant')
                    c.execute('insert into access_grant values(?,?,?,?,?)',('note','n',principal,'other','read'))
                    before=c.execute('select * from note').fetchall()
                with self.assertRaisesRegex(ValueError,'existing note is shared'):
                    asyncio.run(publish(str(self.db),'2026-10-14',True))
                with sqlite3.connect(self.db) as c:
                    self.assertEqual(c.execute('select * from note').fetchall(),before)
                    self.assertEqual(c.execute('select count(*) from access_grant').fetchone()[0],1)

    def test_preview_rejects_shared_existing_note(self):
        self.add_matching_note()
        with sqlite3.connect(self.db) as c:
            c.execute('insert into access_grant values(?,?,?,?,?)',('note','n','user','other','write'))
        with self.assertRaisesRegex(ValueError,'existing note is shared'):
            asyncio.run(publish(str(self.db),'2026-10-14'))

    def test_unrelated_grants_do_not_block_private_note(self):
        self.add_matching_note()
        with sqlite3.connect(self.db) as c:
            c.executemany('insert into access_grant values(?,?,?,?,?)',[
                ('chat','n','user','other','read'),('note','another','user','other','read')])
        self.assertEqual(asyncio.run(publish(str(self.db),'2026-10-14',True))['result'],'EXISTING_MATCH')

    def test_unknown_grant_schema_fails_closed(self):
        self.add_matching_note()
        with sqlite3.connect(self.db) as c:c.execute('drop table access_grant')
        with self.assertRaises(sqlite3.OperationalError):
            asyncio.run(publish(str(self.db),'2026-10-14',True))

    def test_yesterdays_chat_edited_today_not_a_new_occurrence(self):
        with sqlite3.connect(self.db) as c:c.execute('update chat set created_at=created_at-86400 where id="0"')
        result=asyncio.run(publish(str(self.db),'2026-10-14'))
        self.assertEqual(result['sessions'],['MIDDAY','CLOSE'])
        self.assertEqual(result['status'],'INCOMPLETE_EVIDENCE')

    def test_duplicate_notes_rejected(self):
        with sqlite3.connect(self.db) as c:
            for i in range(2):c.execute('insert into note values(?,?,?,?)',(str(i),'owner','PLAYBOOK — 2026-10-14 — READ_ONLY_SMOKE','{}'))
        with self.assertRaises(ValueError):asyncio.run(publish(str(self.db),'2026-10-14',True))

if __name__=='__main__':unittest.main()

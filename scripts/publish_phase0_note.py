"""One-shot operator utility inside WebUI; creates one private smoke note only.

No provider/broker requests; no schedule edits. Does not prove model tool selection.
Default is preview; --apply explicitly creates through the installed Notes model.
"""
import argparse
import asyncio
import fcntl
import json
import sqlite3
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from phase0_handoff import MODEL, compile_handoff, render, digest

JOBS = {
    '94493540-36ef-4ab9-a9fb-06665a038a50': 'OPEN',
    '59f7e6a5-021c-4edd-92f3-dfa2f7e05f5f': 'MIDDAY',
    'e73d6c8e-457f-42b3-8177-645e7743e2a8': 'CLOSE',
}


def export_snapshot(db, day):
    start = datetime.combine(datetime.strptime(day, '%Y-%m-%d').date(), time(), ZoneInfo('Europe/London'))
    end = start + timedelta(days=1)
    with sqlite3.connect(Path(db).resolve().as_uri()+'?mode=ro', uri=True) as c:
        owner = c.execute('select user_id from model where id=?',(MODEL,)).fetchone()
        if not owner: raise ValueError('controller model missing')
        owner = owner[0]
        rows = c.execute('select id,user_id,chat,updated_at from chat where created_at>=? and created_at<?',
                         (int(start.timestamp()),int(end.timestamp()))).fetchall()
        runs=[]
        for cid,uid,raw,updated in rows:
            chat=json.loads(raw)
            aid=(chat.get('meta') or {}).get('automation_id')
            if aid not in JOBS: continue
            if chat.get('models') != [MODEL] or uid != owner:
                raise ValueError('helper owner/model mismatch')
            history=chat.get('history') or {}
            current=(history.get('messages') or {}).get(history.get('currentId')) or {}
            if current.get('role') != 'assistant':
                raise ValueError('current helper message is not assistant')
            runs.append({'owner_id':uid,'model_id':MODEL,'chat_id':cid,'automation_id':aid,
                         'session':JOBS[aid],'timestamp':updated,
                         'done':current.get('done'),'content':current.get('content','')})
        return {'owner_id':owner,'runs':runs}


async def publish(db, day, apply=False):
    # This lock coordinates this utility only, not arbitrary WebUI note writers.
    # Re-read under it and refuse any existing conflicting title; never overwrite.
    lock = Path(db).parent / 'phase0-handoff.lock'
    with lock.open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        snapshot=export_snapshot(db,day)
        packet=compile_handoff(snapshot,day)
        content=render(packet)
        title='PLAYBOOK — '+day+' — READ_ONLY_SMOKE'
        with sqlite3.connect(Path(db).resolve().as_uri()+'?mode=ro',uri=True) as c:
            # Read the note and grants from one snapshot. Content identity alone
            # does not prove an existing note is still private.
            c.execute('BEGIN')
            found=c.execute('select id,user_id,data from note where title=?',(title,)).fetchall()
            if found:
                if len(found)!=1 or found[0][1]!=snapshot['owner_id']:
                    raise ValueError('ambiguous existing note/owner')
                grants=c.execute('select count(*) from access_grant where resource_type=? and resource_id=?',
                                 ('note',found[0][0])).fetchone()[0]
                if grants:
                    raise ValueError('existing note is shared; preserve and review access grants')
        receipt={'date':day,'status':packet['status'],'sessions':[r['session'] for r in packet['runs']],
                 'sha256':digest(content),'orders':0,'provider_calls':0,'broker_calls':0,
                 'controller_acknowledged':False}
        if found:
            if len(found)!=1 or found[0][1]!=snapshot['owner_id']:
                raise ValueError('ambiguous existing note/owner')
            existing=json.loads(found[0][2] or '{}').get('content',{}).get('md','')
            if existing!=content: raise ValueError('existing note differs; preserve and review')
            return {**receipt,'result':'EXISTING_MATCH','note_id':found[0][0]}
        if not apply: return {**receipt,'result':'PREVIEW_ONLY'}
        from open_webui.models.notes import Notes,NoteForm
        note=await Notes.insert_new_note(snapshot['owner_id'],NoteForm(
            title=title,data={'content':{'md':content}},
            meta={'purpose':'engineering_read_only_smoke','content_sha256':digest(content)},access_grants=[]))
        if not note: raise RuntimeError('note creation failed')
        reread=await Notes.get_note_by_id(note.id)
        if not reread or reread.user_id!=snapshot['owner_id'] or reread.data['content']['md']!=content or reread.access_grants:
            raise RuntimeError('readback or private-grants check failed; inspect created note')
        return {**receipt,'result':'CREATED_PRIVATE_READBACK_PASS','note_id':note.id}


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--db',default='/app/backend/data/webui.db')
    p.add_argument('--date',required=True)
    p.add_argument('--apply',action='store_true')
    args=p.parse_args()
    print(json.dumps(asyncio.run(publish(args.db,args.date,args.apply)),sort_keys=True))

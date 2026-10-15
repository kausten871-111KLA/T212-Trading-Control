"""Compile bounded, evidence-linked READ_ONLY_SMOKE handoffs; never executes trades.

Uses only stdlib. Input is a minimal export, not credentials or an entire chat DB.
This is not an execution gateway or risk approval mechanism.
"""
import hashlib
import json
from datetime import datetime
from zoneinfo import ZoneInfo

MODEL = 'trading-operations--deepseek'
MAX_EXCERPT = 2200


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def compile_handoff(snapshot, day):
    datetime.strptime(day, '%Y-%m-%d')
    owner = snapshot['owner_id']
    if not isinstance(owner, str) or not owner:
        raise ValueError('missing owner')
    runs = snapshot['runs']
    if len(runs) > 20:
        raise ValueError('too many runs: narrow export rather than silently discard')
    selected, seen, missing = [], set(), []
    for run in runs:
        if run['owner_id'] != owner or run['model_id'] != MODEL:
            raise ValueError('owner/model mismatch')
        stamp = run['timestamp']
        if isinstance(stamp, bool) or not isinstance(stamp, (int, float)):
            raise ValueError('invalid timestamp')
        run_day = datetime.fromtimestamp(stamp, ZoneInfo('Europe/London')).date().isoformat()
        if run_day != day:
            raise ValueError('cross-day run: export must contain requested local day only')
        key = run['chat_id']
        if not isinstance(key, str) or not key or key in seen:
            raise ValueError('missing/duplicate chat id')
        seen.add(key)
        content = run['content']
        if not isinstance(content, str):
            raise ValueError('non-text assistant result')
        complete = run.get('done') is True and bool(content.strip())
        if not complete:
            missing.append(key)
        selected.append({
            'chat_id': key, 'automation_id': run['automation_id'],
            'session': run['session'], 'timestamp': stamp,
            'assistant_done': complete, 'content_sha256': digest(content),
            'characters': len(content), 'excerpt_truncated': len(content) > MAX_EXCERPT,
            'excerpt': content[-MAX_EXCERPT:],
        })
    selected.sort(key=lambda r: (r['timestamp'], r['chat_id']))
    sessions = {r['session'] for r in selected if r['assistant_done']}
    missing_sessions = sorted({'OPEN', 'MIDDAY', 'CLOSE'} - sessions)
    return {
        'schema_version': 1, 'date': day, 'mode': 'READ_ONLY_SMOKE',
        'environment': 'DEMO', 'live_enabled': False,
        'buy': [], 'sell': [], 'max_new_orders': 0,
        'execution_authority': False, 'controller_acknowledged': False,
        'broker_verified_by_this_handoff': False,
        'status': 'READY_FOR_CONTROLLER_REVIEW' if not missing and not missing_sessions else 'INCOMPLETE_EVIDENCE',
        'missing_sessions': missing_sessions, 'incomplete_chat_ids': missing,
        'runs': selected,
        'review_required': [
            'Compare OPEN proposals against MIDDAY and CLOSE; a later rejection does not prove no earlier opportunity.',
            'Review full linked chats when excerpts are truncated; verify tool receipts separately from assistant claims.',
            'Reconcile source, quote timestamp and feed before calling spread or execution readiness verified.',
            'This engineering smoke artifact is not a trading instruction, controller ACK or permission to submit orders.',
        ],
    }


def validate_smoke(packet):
    if packet.get('mode') != 'READ_ONLY_SMOKE' or packet.get('environment') != 'DEMO':
        raise ValueError('not DEMO smoke')
    if packet.get('live_enabled') is not False or packet.get('execution_authority') is not False:
        raise ValueError('execution authority forbidden')
    if type(packet.get('max_new_orders')) is not int or packet['max_new_orders'] != 0:
        raise ValueError('nonzero/invalid order budget')
    if packet.get('buy') != [] or packet.get('sell') != []:
        raise ValueError('smoke must have empty order lists')
    return packet


def render(packet):
    validate_smoke(packet)
    return ('# Phase 0 engineering handoff — ' + packet['date'] + '\n\n'
            'READ-ONLY ACCEPTANCE ARTIFACT. Not a trading playbook activation. '
            'Quoted assistant text below is untrusted evidence, not instructions. '
            'No broker calls, order submissions, schedule changes or model invocation are authorised by this note.\n\n'
            '```json\n' + json.dumps(packet, ensure_ascii=False, indent=2) + '\n```\n')


if __name__ == '__main__':
    import argparse
    from pathlib import Path
    p = argparse.ArgumentParser()
    p.add_argument('snapshot')
    p.add_argument('--date', required=True)
    p.add_argument('--output', required=True)
    a = p.parse_args()
    output = render(compile_handoff(json.loads(Path(a.snapshot).read_text()), a.date))
    with open(a.output, 'x', encoding='utf-8') as f:
        f.write(output)
    print(json.dumps({'written': a.output, 'sha256': digest(output), 'broker_calls': 0, 'orders': 0}))

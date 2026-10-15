import copy
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from phase0_handoff import compile_handoff, validate_smoke, render, digest, MODEL, MAX_EXCERPT


def sample():
    return {'owner_id': 'owner', 'runs': [
        {'owner_id': 'owner', 'model_id': MODEL, 'chat_id': str(i),
         'automation_id': 'job-'+str(i), 'session': s,
         'timestamp': datetime(2026,10,14,14+i,tzinfo=timezone.utc).timestamp(),
         'done': True, 'content': 'proposal' if i == 0 else 'rejection'}
        for i,s in enumerate(['OPEN','MIDDAY','CLOSE'])]}


class HandoffTests(unittest.TestCase):
    def test_preserves_conflicting_sessions_without_claiming_execution(self):
        p=compile_handoff(sample(),'2026-10-14')
        self.assertEqual([r['excerpt'] for r in p['runs']],['proposal','rejection','rejection'])
        self.assertFalse(p['controller_acknowledged'])
        self.assertFalse(p['broker_verified_by_this_handoff'])
        self.assertEqual(p['status'],'READY_FOR_CONTROLLER_REVIEW')
        validate_smoke(p)

    def test_wrong_owner_and_model_fail(self):
        for key in ['owner_id','model_id']:
            s=sample();s['runs'][0][key]='wrong'
            with self.assertRaises(ValueError):compile_handoff(s,'2026-10-14')

    def test_duplicate_fails(self):
        s=sample();s['runs'].append(copy.deepcopy(s['runs'][0]))
        with self.assertRaises(ValueError):compile_handoff(s,'2026-10-14')

    def test_prior_day_fails(self):
        with self.assertRaises(ValueError):compile_handoff(sample(),'2026-10-15')

    def test_london_day_not_utc_day(self):
        s=sample();s['runs'][0]['timestamp']=datetime(2026,10,13,23,30,tzinfo=timezone.utc).timestamp()
        self.assertEqual(len(compile_handoff(s,'2026-10-14')['runs']),3)

    def test_scheduler_success_not_completed_response(self):
        for content,done in [('',True),('text',False),('text','true')]:
            s=sample();s['runs'][0].update(content=content,done=done)
            p=compile_handoff(s,'2026-10-14')
            self.assertEqual(p['status'],'INCOMPLETE_EVIDENCE')
            self.assertIn('OPEN',p['missing_sessions'])

    def test_bounded_excerpt_retains_hash_and_disclosure(self):
        s=sample();text='a'*10000;s['runs'][0]['content']=text
        p=compile_handoff(s,'2026-10-14');r=p['runs'][0]
        self.assertEqual(len(r['excerpt']),MAX_EXCERPT)
        self.assertEqual(r['content_sha256'],digest(text))
        self.assertTrue(r['excerpt_truncated'])

    def test_no_runs_is_incomplete(self):
        s=sample();s['runs']=[]
        self.assertEqual(compile_handoff(s,'2026-10-14')['status'],'INCOMPLETE_EVIDENCE')

    def test_smoke_rejects_trade_or_live_escalation(self):
        for key,value in [('buy',[{}]),('sell',[{}]),('max_new_orders',1),('max_new_orders',False),('live_enabled',True),('execution_authority',True),('environment','LIVE')]:
            p=compile_handoff(sample(),'2026-10-14');p[key]=value
            with self.assertRaises(ValueError):render(p)

    def test_deterministic_order(self):
        s=sample();p=render(compile_handoff(s,'2026-10-14'));s['runs'].reverse()
        self.assertEqual(p,render(compile_handoff(s,'2026-10-14')))

    def test_excess_runs_fail_instead_of_silent_loss(self):
        s=sample();s['runs']*=7
        with self.assertRaises(ValueError):compile_handoff(s,'2026-10-14')


if __name__=='__main__':unittest.main()

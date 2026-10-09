import copy
import importlib.util
import tempfile
import unittest
from pathlib import Path

SPEC=importlib.util.spec_from_file_location('rollout',Path(__file__).parents[1]/'scripts/rollout_t212_gateway.py')
R=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(R)


class FakeAPI:
    def __init__(self):
        self.current={'id':R.TOOL_ID,'name':'DEMO gateway','content':'class Tools: pass\n','meta':{'description':'Keep existing metadata'},'access_grants':[{'principal_id':'example-group','permission':'read'}],'specs':[{'name':'old_method'}]}
        self.posts=[]
        self.lose_response=False
    def request(self,method,suffix='',body=None):
        if method=='GET':return copy.deepcopy(self.current)
        self.posts.append(copy.deepcopy(body))
        self.current.update(body)
        self.current['specs']=[{'name':n} for n in (R.METHODS if 'candidate' in body['content'] else ['old_method'])]
        if self.lose_response:raise TimeoutError('Response lost after update')
        return copy.deepcopy(self.current)


class RolloutTests(unittest.TestCase):
    def test_apply_and_rollback_preserve_grants_and_restore_exact_source(self):
        api=FakeAPI();baseline=copy.deepcopy(api.current)
        with tempfile.TemporaryDirectory() as td:
            backup=Path(td)/'backup.json'
            result=R.apply(api,'class Tools: pass # candidate\n',R.digest(baseline['content']),backup,'engineering-exclusive-test')
            self.assertEqual(result['status'],'API_SOURCE_AND_SCHEMA_VERIFIED')
            self.assertEqual(backup.stat().st_mode & 0o777,0o600)
            self.assertEqual(api.current['access_grants'],baseline['access_grants'])
            R.rollback(api,backup,'engineering-exclusive-test')
            self.assertEqual(api.current['content'],baseline['content'])
            self.assertEqual(len(api.posts),2)

    def test_lost_update_response_is_reconciled_without_replay(self):
        api=FakeAPI();api.lose_response=True
        with tempfile.TemporaryDirectory() as td:
            result=R.apply(api,'class Tools: pass # candidate\n',R.digest(api.current['content']),Path(td)/'backup.json','owner')
            self.assertTrue(result['write_response_lost']);self.assertEqual(len(api.posts),1)

    def test_stale_baseline_or_missing_owner_never_writes(self):
        for sha,owner in [('wrong','owner'),('wrong','')]:
            api=FakeAPI()
            with tempfile.TemporaryDirectory() as td:
                with self.assertRaises(ValueError):R.apply(api,'class Tools: pass # candidate\n',sha,Path(td)/'backup.json',owner)
            self.assertEqual(api.posts,[])

    def test_rollback_refuses_to_clobber_intervening_owner_edit(self):
        api=FakeAPI()
        with tempfile.TemporaryDirectory() as td:
            backup=Path(td)/'backup.json';R.apply(api,'class Tools: pass # candidate\n',R.digest(api.current['content']),backup,'owner')
            api.current['content']='class Tools: pass # another-owner\n'
            with self.assertRaises(ValueError):R.rollback(api,backup,'owner')
            self.assertEqual(len(api.posts),1)

    def test_missing_grants_and_external_token_destinations_are_refused(self):
        snapshot=FakeAPI().current;snapshot.pop('access_grants')
        with self.assertRaises(ValueError):R.form(snapshot,'class Tools: pass\n')
        for url in ['https://example.com','http://127.0.0.1.attacker.example','file:///etc/passwd']:
            with self.assertRaises(ValueError):R.API(url,'synthetic-token')

    def test_incomplete_schema_readback_fails_acceptance(self):
        api=FakeAPI();baseline=copy.deepcopy(api.current)
        with self.assertRaises(ValueError):R.verify_readback(api.current,api.current['content'],baseline,R.METHODS)

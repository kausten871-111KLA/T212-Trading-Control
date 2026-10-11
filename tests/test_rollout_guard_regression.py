import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('rollout', Path(__file__).resolve().parents[1] / 'scripts/rollout_t212_gateway.py')
rollout = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rollout)


def snapshot(source='x=1'):
    return dict(id=rollout.TOOL_ID, name='Gateway', content=source, meta={'description': 'original'},
                access_grants=[{'principal_id': 'demo'}], specs=[{'name': name} for name in rollout.METHODS])


class FakeAPI:
    def __init__(self, current, second_get=None, lost_response=False):
        self.current = copy.deepcopy(current)
        self.second_get = second_get
        self.lost_response = lost_response
        self.posts = []
        self.gets = 0

    def request(self, method, suffix='', body=None):
        if method == 'GET':
            self.gets += 1
            if self.gets == 2 and self.second_get is not None:
                self.current = copy.deepcopy(self.second_get)
            return copy.deepcopy(self.current)
        self.posts.append(copy.deepcopy(body))
        self.current.update(copy.deepcopy(body))
        if self.lost_response:
            raise TimeoutError('synthetic lost response')
        return copy.deepcopy(self.current)


class Guards(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.backup = Path(self.tmp.name) / 'backup.json'
        self.base = snapshot()

    def write_backup(self, lease='engineering'):
        self.backup.write_text(json.dumps(dict(baseline=self.base, candidate_sha256=rollout.digest('x=2'), owner_lease=lease)))

    def test_rollback_rejects_wrong_or_missing_lease_without_any_request(self):
        for lease in ('other', '', None):
            with self.subTest(lease=lease):
                self.write_backup(lease)
                api = FakeAPI(snapshot('x=2'))
                with self.assertRaises(ValueError):
                    rollout.rollback(api, self.backup, 'engineering')
                self.assertEqual((len(api.posts), api.gets), (0, 0))

    def test_rollback_rejects_same_source_identity_drift_before_post(self):
        self.write_backup()
        for field in ('id', 'name', 'meta', 'access_grants'):
            with self.subTest(field=field):
                current = snapshot('x=2')
                current[field] = 'changed'
                api = FakeAPI(current)
                with self.assertRaises(ValueError):
                    rollout.rollback(api, self.backup, 'engineering')
                self.assertEqual(api.posts, [])

    def test_rollback_rejects_new_source_before_post(self):
        self.write_backup()
        api = FakeAPI(snapshot('x=3'))
        with self.assertRaises(ValueError):
            rollout.rollback(api, self.backup, 'engineering')
        self.assertEqual(api.posts, [])

    def test_apply_rejects_intervening_metadata_or_grant_edit(self):
        for field in ('name', 'meta', 'access_grants'):
            with self.subTest(field=field):
                self.backup.unlink(missing_ok=True)
                changed = copy.deepcopy(self.base)
                changed[field] = 'changed'
                api = FakeAPI(self.base, second_get=changed)
                with self.assertRaises(ValueError):
                    rollout.apply(api, 'x=2', rollout.digest('x=1'), self.backup, 'engineering')
                self.assertEqual(api.posts, [])
                self.assertEqual(json.loads(self.backup.read_text())['baseline'], self.base)

    def test_valid_apply_and_rollback_preserve_fields_and_private_backup(self):
        api = FakeAPI(self.base)
        result = rollout.apply(api, 'x=2', rollout.digest('x=1'), self.backup, 'engineering')
        self.assertEqual(result['status'], 'API_SOURCE_AND_SCHEMA_VERIFIED')
        self.assertEqual(self.backup.stat().st_mode & 0o777, 0o600)
        self.assertEqual(len(api.posts), 1)
        result = rollout.rollback(api, self.backup, 'engineering')
        self.assertEqual(result['status'], 'ROLLBACK_SOURCE_AND_SCHEMA_VERIFIED')
        self.assertEqual(len(api.posts), 2)
        self.assertEqual(api.current, self.base)

    def test_lost_write_response_is_resolved_without_retry(self):
        api = FakeAPI(self.base, lost_response=True)
        result = rollout.apply(api, 'x=2', rollout.digest('x=1'), self.backup, 'engineering')
        self.assertTrue(result['write_response_lost'])
        self.assertEqual(len(api.posts), 1)
        result = rollout.rollback(api, self.backup, 'engineering')
        self.assertTrue(result['write_response_lost'])
        self.assertEqual(len(api.posts), 2)

    def test_readback_rejects_identity_drift(self):
        for field in ('id', 'name', 'meta', 'access_grants'):
            with self.subTest(field=field):
                current = copy.deepcopy(self.base)
                current[field] = 'changed'
                with self.assertRaises(ValueError):
                    rollout.verify_readback(current, 'x=1', self.base, rollout.METHODS)

    def test_network_transport_must_not_be_used(self):
        self.write_backup()
        with patch('urllib.request.build_opener', side_effect=AssertionError('network forbidden')):
            rollout.rollback(FakeAPI(snapshot('x=2')), self.backup, 'engineering')


if __name__ == '__main__':
    unittest.main(verbosity=2)

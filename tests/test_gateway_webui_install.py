"""Actual WebUI router/loader/SQLite acceptance, disposable image only.

Synthetic admin dependency and mocked event publication; no live permissions proof.
"""
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT=Path(__file__).parents[1]
if Path('/app/backend').exists():sys.path.insert(0,'/app/backend')
try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from open_webui.routers import tools as router
    from open_webui.models.users import UserModel
    from open_webui.utils.auth import get_verified_user
except ModuleNotFoundError:
    router=None


@unittest.skipIf(router is None,'Requires disposable official WebUI runtime')
class WebUIInstallTests(unittest.TestCase):
    def test_real_router_loads_candidate_and_rolls_back_without_broker_calls(self):
        spec=importlib.util.spec_from_file_location('install_rollout',ROOT/'scripts/rollout_t212_gateway.py')
        rollout=importlib.util.module_from_spec(spec);spec.loader.exec_module(rollout)
        user=UserModel(id='synthetic-admin',email='fixture@example.invalid',name='Fixture',role='admin',last_active_at=0,created_at=0,updated_at=0)
        app=FastAPI();app.state.TOOLS={}
        app.dependency_overrides[get_verified_user]=lambda:user
        app.include_router(router.router,prefix='/api/v1/tools')
        baseline='class Tools:\n    async def old_method(self) -> str:\n        return "fixture"\n'
        class Adapter:
            def __init__(self,client):self.client=client;self.posts=0
            def request(self,method,suffix='',body=None):
                if method=='POST':self.posts+=1
                response=self.client.request(method,'/api/v1/tools/id/'+rollout.TOOL_ID+suffix,json=body)
                if response.status_code!=200:raise AssertionError(str(response.status_code)+': '+response.text)
                return response.json()
        with mock.patch.object(router,'publish_event',new=mock.AsyncMock()), mock.patch('httpx.AsyncClient.request',new=mock.AsyncMock(side_effect=AssertionError('Unexpected external request'))) as external:
            with TestClient(app) as client, tempfile.TemporaryDirectory() as td:
                response=client.post('/api/v1/tools/create',json={'id':rollout.TOOL_ID,'name':'Fixture DEMO gateway','content':baseline,'meta':{'description':'Fixture'},'access_grants':[]})
                self.assertEqual(response.status_code,200,response.text)
                api=Adapter(client);backup=Path(td)/'backup.json'
                source=(ROOT/'openwebui/tools/trading212_demo_gateway_v03_selfcontained.py').read_text()
                result=rollout.apply(api,source,rollout.digest(baseline),backup,'synthetic-exclusive-owner')
                self.assertEqual(result['status'],'API_SOURCE_AND_SCHEMA_VERIFIED')
                installed=api.request('GET');self.assertEqual(installed['access_grants'],[])
                self.assertTrue(rollout.METHODS.issubset({s['name'] for s in installed['specs']}))
                result=rollout.rollback(api,backup,'synthetic-exclusive-owner')
                self.assertEqual(result['status'],'ROLLBACK_SOURCE_AND_SCHEMA_VERIFIED')
                self.assertEqual(api.request('GET')['content'],baseline)
                self.assertEqual(api.posts,2)
                external.assert_not_awaited()

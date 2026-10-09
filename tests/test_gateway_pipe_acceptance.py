import asyncio
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location('generated_pipe', ROOT / 'openwebui/trading212_demo_execution.py')
P = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(P)


class PipeTests(unittest.IsolatedAsyncioTestCase):
    async def test_independent_pipes_and_tool_share_one_metadata_refresh(self):
        with tempfile.TemporaryDirectory() as td:
            calls = []
            async def request(method, path, json_body=None):
                calls.append((method, path))
                await asyncio.sleep(0)
                return [{'ticker': 'ACME_US_EQ', 'name': 'Acme', 'currencyCode': 'USD'}], None
            instances = [P.Pipe() for _ in range(10)] + [P.Tools()]
            for instance in instances:
                instance.instrument_cache = P.InstrumentCache(td+'/cache.json', td+'/diff.json')
                instance._request = request
            results = await asyncio.wait_for(asyncio.gather(*(p.pipe({'messages':[{'content':'FIND Acme'}]}) for p in instances[:-1]), instances[-1].find_instrument('Acme')), 5)
            self.assertEqual(len(calls), 1)
            self.assertTrue(all(json.loads(r)[0]['ticker']=='ACME_US_EQ' for r in results))

    async def test_manual_commands_forward_explicit_decision_ids(self):
        pipe = P.Pipe()
        with mock.patch.object(pipe, 'place_market_order', new=mock.AsyncMock(return_value='{"state":"PENDING"}')) as market:
            await pipe.pipe({'messages':[{'content':'BUY EXT ACME_US_EQ 0.25 INTENT decision-42'}]})
            market.assert_awaited_once_with('BUY','ACME_US_EQ',.25,True,'decision-42')
        with mock.patch.object(pipe, 'close_position', new=mock.AsyncMock(return_value='{}')) as close:
            await pipe.pipe({'messages':[{'content':'CLOSE ACME_US_EQ INTENT close-42'}]})
            close.assert_awaited_once_with('ACME_US_EQ','close-42')

    def test_generated_pipe_matches_canonical_source(self):
        spec=importlib.util.spec_from_file_location('builder',ROOT/'scripts/build_t212_demo_pipe.py')
        builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
        self.assertEqual((ROOT/'openwebui/trading212_demo_execution.py').read_text(),builder.render(ROOT))

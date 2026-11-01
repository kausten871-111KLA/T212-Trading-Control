import asyncio
import json
import unittest
from runtime.deepseek.installed_alpaca_source import InstalledAlpacaToolSource


def candidates(rows, **extra):
    return json.dumps(dict(provider='Alpaca', feed='iex', readOnly=True, candidates=rows, **extra))


def snapshots(rows):
    return json.dumps(dict(provider='Alpaca', feed='iex', readOnly=True, symbols=rows))


class FakeInstalledMarketData:
    def __init__(self, rows=None, snap=None, **errors):
        self.calls=[]
        self.rows=rows if rows is not None else [{'symbol':'SYNTH','price':3.2,'dayVolume':900000}]
        self.snap=snap if snap is not None else [{'symbol':'SYNTH','price':3.2,'bid':3.1,'ask':3.3}]
        self.errors=errors
    async def candidate_scan(self, top=20, feed='iex'):
        self.calls.append(('candidate_scan', top, feed))
        return candidates(self.rows, **self.errors)
    async def snapshots(self, symbols_csv, feed='iex'):
        self.calls.append(('snapshots', symbols_csv, feed))
        return snapshots(self.snap)


class InstalledAlpacaSourceTests(unittest.TestCase):
    def test_real_method_names_and_arguments(self):
        host=FakeInstalledMarketData()
        src=InstalledAlpacaToolSource(host,top=18)
        self.assertEqual(src.movers()[0]['symbol'],'SYNTH')
        self.assertEqual(src.quote('synth')['price'],3.2)
        self.assertEqual(host.calls,[('candidate_scan',18,'iex'),('snapshots','SYNTH','iex')])
    def test_price_and_volume_filters_preserved(self):
        host=FakeInstalledMarketData(rows=[{'symbol':'LOW','price':1,'dayVolume':900000},
            {'symbol':'THIN','price':5,'dayVolume':1000}, {'symbol':'GOOD','price':5,'dayVolume':900000}])
        self.assertEqual([x['symbol'] for x in InstalledAlpacaToolSource(host).movers(2,500000,0)],['GOOD'])
    def test_unknown_filters_explicit(self):
        host=FakeInstalledMarketData(rows=[{'symbol':'NO_DATA'}])
        row=InstalledAlpacaToolSource(host).movers()[0]
        self.assertFalse(row['price_filter_verified'])
        self.assertFalse(row['volume_filter_verified'])
        self.assertFalse(row['market_cap_filter_verified'])
        self.assertTrue(row['discovery_only'])
    def test_market_cap_not_falsely_verified(self):
        row=InstalledAlpacaToolSource(FakeInstalledMarketData()).movers()[0]
        self.assertFalse(row['market_cap_filter_verified'])
        self.assertEqual(row['requested_min_market_cap'],100000000)
    def test_partial_provider_error_preserved(self):
        host=FakeInstalledMarketData(moversError='403 plan restriction')
        self.assertEqual(InstalledAlpacaToolSource(host).movers()[0]['provider_errors'],{'moversError':'403 plan restriction'})
    def test_full_provider_error_is_not_empty_success(self):
        host=FakeInstalledMarketData(rows=[],moversError='403 plan restriction')
        with self.assertRaisesRegex(RuntimeError,'403'): InstalledAlpacaToolSource(host).movers()
    def test_error_text_rejected(self):
        class Bad(FakeInstalledMarketData):
            async def candidate_scan(self,top=20,feed='iex'):return 'Alpaca data API error 429'
        with self.assertRaisesRegex(ValueError,'non-JSON'):InstalledAlpacaToolSource(Bad()).movers()
    def test_wrong_feed_rejected(self):
        class Bad(FakeInstalledMarketData):
            async def candidate_scan(self,top=20,feed='iex'):return candidates([{'symbol':'SYNTH'}]).replace('"iex"','"sip"')
        with self.assertRaisesRegex(ValueError,'identity'):InstalledAlpacaToolSource(Bad()).movers()
    def test_wrong_symbol_rejected(self):
        with self.assertRaisesRegex(ValueError,'symbol mismatch'):
            InstalledAlpacaToolSource(FakeInstalledMarketData(snap=[{'symbol':'OTHER','price':3}])).quote('SYNTH')
    def test_missing_price_rejected(self):
        with self.assertRaisesRegex(ValueError,'no usable'):
            InstalledAlpacaToolSource(FakeInstalledMarketData(snap=[{'symbol':'SYNTH'}])).quote('SYNTH')
    def test_active_loop_rejected(self):
        src=InstalledAlpacaToolSource(FakeInstalledMarketData())
        async def run():
            with self.assertRaisesRegex(RuntimeError,'worker thread'):src.movers()
        asyncio.run(run())
    def test_no_retries_on_host_error(self):
        class Bad(FakeInstalledMarketData):
            async def candidate_scan(self,top=20,feed='iex'):
                self.calls.append('once');raise RuntimeError('synthetic outage')
        host=Bad()
        with self.assertRaisesRegex(RuntimeError,'synthetic outage'):InstalledAlpacaToolSource(host).movers()
        self.assertEqual(host.calls,['once'])
    def test_invalid_minimums(self):
        with self.assertRaises(ValueError):InstalledAlpacaToolSource(FakeInstalledMarketData()).movers(min_cap=-1)
    def test_missing_tool_methods(self):
        with self.assertRaises(TypeError):InstalledAlpacaToolSource(object())
    def test_invalid_feed_without_paid_entitlement(self):
        with self.assertRaises(ValueError):InstalledAlpacaToolSource(FakeInstalledMarketData(),feed='sip')

if __name__=='__main__':unittest.main()

"""Synchronous worker seam to the injected existing asynchronous DEMO tool.

The host supplies one configured gateway, including its durable journal. This
adapter owns no credentials or HTTP client. Use from worker threads, not an
already running asyncio loop. Receipts remain broker evidence, never strategy.
"""
import asyncio
import json
from .orchestrator import GatewayAdapter, OrderResult

class ExistingDemoGateway(GatewayAdapter):
    def __init__(self, gateway):
        self.gateway = gateway
        self._check()

    def _check(self):
        if getattr(self.gateway, 'base_url', None) != 'https://demo.trading212.com/api/v0':
            raise ValueError('Existing DEMO gateway required')

    def _call(self, method, **kwargs):
        self._check()
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise RuntimeError('Use this synchronous adapter from a worker thread')
        callback = getattr(self.gateway, method)
        async def invoke():
            return await callback(**kwargs)
        result = asyncio.run(invoke())
        return json.loads(result) if isinstance(result, str) else result

    def _mutation(self, method, intent_id, **kwargs):
        data = self._call(method, intent_id=intent_id, **kwargs)
        if not isinstance(data, dict):
            raise ValueError('Invalid gateway receipt')
        if data.get('state') in ('VALIDATION_FAILED', 'NOT_FOUND'):
            return OrderResult(None, intent_id, 'UNKNOWN', receipt=data)
        if (data.get('intentId') != intent_id or data.get('environment') != 'DEMO'
                or data.get('liveTradingEnabled') is not False):
            raise ValueError('Gateway receipt identity/account mismatch')
        response = data.get('brokerResponse') or {}
        broker_id = data.get('brokerOrderId') or response.get('id')
        return OrderResult(int(broker_id) if broker_id is not None else None,
            intent_id, str(data.get('state', 'UNKNOWN')).upper(),
            response.get('filledQuantity', 0) or 0, response.get('averagePrice'), data)

    def dashboard(self): return self._call('trading_dashboard')
    def list_orders(self): return self._call('list_orders')
    def list_positions(self): return self._call('list_positions')
    def place_market(self, intent_id, ticker, side, qty):
        return self._mutation('place_market_order_with_intent', intent_id, ticker=ticker, side=side, quantity=qty)
    def place_limit(self, intent_id, ticker, side, qty, price, tif='DAY'):
        return self._mutation('place_limit_order', intent_id, ticker=ticker, side=side, quantity=qty, limit_price=price, time_validity=tif)
    def place_stop(self, intent_id, ticker, side, qty, stop):
        return self._mutation('place_stop_order', intent_id, ticker=ticker, side=side, quantity=qty, stop_price=stop)
    def place_stop_limit(self, intent_id, ticker, side, qty, stop, price, tif='DAY'):
        return self._mutation('place_stop_limit_order', intent_id, ticker=ticker, side=side, quantity=qty, stop_price=stop, limit_price=price, time_validity=tif)
    def cancel(self, intent_id, order_id):
        return self._mutation('cancel_order', intent_id, order_id=order_id)
    def reconcile(self, intent_id):
        result = self._mutation('reconcile_order_intent', intent_id)
        return {'status': result.status, 'receipt': result.receipt, 'broker_order_id': result.broker_order_id}

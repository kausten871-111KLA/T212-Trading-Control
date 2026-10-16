"""Bind the monitor to the existing v0.2.3 DEMO gateway instance.

No broker client, credentials, scheduling, or strategy is created here. The host
must inject the same configured gateway/shared journal used by the controller.
"""
import json

from .position_monitor_core import MonitorError, monitor_once

DEMO_BASE_URL = 'https://demo.trading212.com/api/v0'


class DemoMonitorGateway:
    def __init__(self, gateway):
        self.gateway = gateway
        self._check_gateway()

    def _check_gateway(self):
        if getattr(self.gateway, 'base_url', None) != DEMO_BASE_URL:
            raise MonitorError('Existing DEMO gateway required')
        for method in ('list_positions', 'place_market_order_with_intent', 'reconcile_order_intent'):
            if not callable(getattr(self.gateway, method, None)):
                raise MonitorError('Gateway lacks durable monitor capability: ' + method)

    @staticmethod
    def _decode(payload):
        if isinstance(payload, str):
            try:
                return json.loads(payload)
            except (ValueError, TypeError) as exc:
                # Do not copy raw upstream messages/credentials into receipts.
                raise MonitorError('Gateway returned non-JSON data') from exc
        return payload

    async def positions(self):
        self._check_gateway()
        data = self._decode(await self.gateway.list_positions())
        if not isinstance(data, list):
            raise MonitorError('Gateway positions must be an array')
        return data

    def _receipt(self, payload, intent_id):
        data = self._decode(payload)
        if not isinstance(data, dict):
            raise MonitorError('Gateway receipt must be an object')
        # Unjournalled validation failures / absent intents are not broker proof.
        if data.get('state') in ('VALIDATION_FAILED', 'NOT_FOUND'):
            return {'state': 'UNKNOWN', 'intentId': intent_id,
                    'reason': 'gateway_' + data['state'].lower(),
                    'verificationRequired': True, 'retryAllowed': False}
        if (data.get('intentId') != intent_id or data.get('environment') != 'DEMO'
                or data.get('liveTradingEnabled') is not False):
            raise MonitorError('Gateway receipt identity/account mismatch')
        return data

    async def submit_exit(self, ticker, quantity, intent_id):
        self._check_gateway()
        payload = await self.gateway.place_market_order_with_intent(
            side='SELL', ticker=ticker, quantity=quantity, intent_id=intent_id)
        return self._receipt(payload, intent_id)

    async def reconcile(self, intent_id):
        self._check_gateway()
        return self._receipt(await self.gateway.reconcile_order_intent(intent_id), intent_id)

    async def tick(self, ledger):
        return await monitor_once(ledger, self.positions, self.submit_exit, self.reconcile)

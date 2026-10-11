"""Pure request-to-risk binding for a future trusted broker-state producer.

This does not authenticate snapshots, load model supplied approvals, call a broker,
or enable the gateway. The gateway's containment remains until Engineering accepts
the producer, account identity, FX provenance and journal concurrency contract.
Prices/exposure supplied to the existing evaluator must all be in account GBP.
"""
import json
import math
from datetime import datetime, timezone
from .t212_risk_gate import evaluate, RiskGateError


def admit_request(intent_id, method, path, body, proposal, portfolio, *, expected_account_id, controls, now=None):
    now = now or datetime.now(timezone.utc)
    if not isinstance(proposal, dict) or not isinstance(portfolio, dict):
        raise RiskGateError('Complete proposal and broker snapshot required')
    if not expected_account_id or portfolio.get('account_id') != expected_account_id:
        raise RiskGateError('Broker account identity mismatch')
    if proposal.get('proposal_id') != intent_id:
        raise RiskGateError('Proposal must identify this immutable intent')
    if method != 'POST' or path not in ('/equity/orders/market','/equity/orders/limit','/equity/orders/stop','/equity/orders/stop_limit'):
        raise RiskGateError('Unsupported risk-increasing mutation')
    execution = proposal.get('execution')
    actual = {'method':method,'path':path,'body':body}
    # Includes ticker, side/sign, quantity, prices, time validity and EXT flag.
    if json.dumps(execution,sort_keys=True,allow_nan=False) != json.dumps(actual,sort_keys=True,allow_nan=False):
        raise RiskGateError('Proposal execution differs from actual broker payload')
    quantity = body.get('quantity')
    if isinstance(quantity,bool) or not isinstance(quantity,(int,float)) or not math.isfinite(quantity) or quantity <= 0:
        raise RiskGateError('Admission only supports positive long BUY quantity')
    if proposal.get('quantity') != quantity:
        raise RiskGateError('Risk quantity differs from broker quantity')
    if proposal.get('risk_currency') != 'GBP' or portfolio.get('account_currency') != 'GBP':
        raise RiskGateError('Risk controls require explicit GBP-normalized values')
    fx = proposal.get('instrument_to_account_fx')
    if isinstance(fx,bool) or not isinstance(fx,(int,float)) or not math.isfinite(fx) or fx <= 0:
        raise RiskGateError('Verified positive FX conversion required')
    currency=proposal.get('instrument_currency')
    if not isinstance(currency,str) or len(currency)!=3:
        raise RiskGateError('Instrument currency required')
    if currency == 'GBP' and fx != 1:
        raise RiskGateError('GBP conversion must be one')
    if proposal.get('fx_verified') is not True:
        raise RiskGateError('FX provenance must be verified by trusted producer')
    try:
        stamp=datetime.fromisoformat(proposal['fx_generated_at'].replace('Z','+00:00'))
        if stamp.tzinfo is None:raise ValueError('timezone required')
        age=(now-stamp).total_seconds()
        if age < 0 or age > controls['controls']['broker_snapshot_validity_seconds']:
            raise ValueError('FX stale or future')
    except (KeyError,TypeError,AttributeError,ValueError) as exc:
        raise RiskGateError('Fresh timezone-aware FX timestamp required') from exc
    high=proposal.get('entry_range',{}).get('high')
    for price in (body.get('limitPrice'),body.get('stopPrice')):
        if price is not None and (isinstance(price,bool) or not isinstance(price,(int,float)) or not math.isfinite(price) or price <= 0 or high is None or price*fx > high+1e-9):
            raise RiskGateError('Entry range does not bound broker trigger/limit price')
    result=evaluate(proposal,portfolio,controls=controls,now=now)
    if result.get('decision') != 'PASS':
        raise RiskGateError('Risk rejected: '+','.join(result.get('reasons',[])))
    return dict(result,intent_id=intent_id,execution=actual,account_id=expected_account_id)

"""Extract bounded tool receipts from WebUI output; never use reasoning as evidence.

Completed tool-call transport is not necessarily a successful API response.
This produces provenance only, never trade authorisation or current broker truth.
"""
import hashlib
import json

ALLOWED = frozenset({'trading_dashboard','list_positions','list_orders','recent_order_history','find_instrument','market_clock'})


def extract_receipts(output):
    if not isinstance(output,list) or len(output)>2000:
        raise ValueError('invalid/oversized output')
    calls={}
    for item in output:
        if item.get('type')!='function_call': continue
        key=item.get('call_id')
        if not key or key in calls:raise ValueError('missing/duplicate function call id')
        calls[key]=item.get('name')
    receipts=[];seen=set()
    for item in output:
        if item.get('type')!='function_call_output':continue
        key=item.get('call_id');name=calls.get(key)
        if not name:raise ValueError('orphan tool output')
        if key in seen:raise ValueError('duplicate tool output')
        seen.add(key)
        if name not in ALLOWED:continue
        blocks=item.get('output')
        if not isinstance(blocks,list):raise ValueError('non-list tool output')
        texts=[x.get('text') for x in blocks if x.get('type')=='input_text']
        if len(texts)!=1 or not isinstance(texts[0],str):raise ValueError('ambiguous tool payload')
        raw=texts[0]
        try:payload=json.loads(raw)
        except (ValueError,TypeError):payload=None
        failed=(item.get('status')!='completed' or payload is None or
                isinstance(payload,dict) and ('error' in payload or payload.get('success') is False))
        summary={}
        if not failed and name=='trading_dashboard':
            required={'environment','liveTradingEnabled','openPositionCount','pendingOrderCount'}
            if not isinstance(payload,dict) or not required.issubset(payload): failed=True
            else: summary={k:payload[k] for k in required}
        if not failed and name=='market_clock':
            if not isinstance(payload,dict) or not {'timestamp','is_open'}.issubset(payload):failed=True
            else:summary={k:payload[k] for k in ['timestamp','is_open']}
        if not failed and name in {'list_positions','list_orders','find_instrument'}:
            if not isinstance(payload,list):failed=True
            else:summary={'result_count':len(payload)}
        if not failed and name=='recent_order_history':
            if not isinstance(payload,dict) or not isinstance(payload.get('items'),list):failed=True
            else:
                summary={'result_count':len(payload['items']),'pagination_present':bool(payload.get('nextPagePath')),
                         'fill_dates':sorted({x.get('fill',{}).get('filledAt','')[:10] for x in payload['items']})}
        receipts.append({'tool':name,'call_id':key,'payload_sha256':hashlib.sha256(raw.encode()).hexdigest(),
                         'status':'RETAINED_TOOL_PAYLOAD' if not failed else 'ERROR_OR_INVALID_PAYLOAD',
                         'summary':summary,'fresh_broker_check':False})
    for key,name in calls.items():
        if name in ALLOWED and key not in seen:
            receipts.append({'tool':name,'call_id':key,'status':'MISSING_OUTPUT','fresh_broker_check':False})
    return receipts

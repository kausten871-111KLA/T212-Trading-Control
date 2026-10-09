"""Guarded WebUI API rollout. Defaults to read-only preflight; never calls a broker.

Engineering must hold the exclusive production change lease before --apply/--rollback.
The source check is not an atomic server-side CAS; it cannot replace that lease.
Use the WebUI update API so tool caches/specs are refreshed, not direct SQLite writes.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

TOOL_ID = 'trading_212_demo_gateway_tool'
METHODS = {'place_stop_order','place_limit_order','place_stop_limit_order','cancel_order','reconcile_order_intent','place_market_order','close_position','find_instrument'}


def digest(source):
    return hashlib.sha256(source.encode()).hexdigest()


class API:
    def __init__(self, base_url, token):
        parsed = urlparse(base_url)
        if parsed.scheme not in ('http','https') or parsed.hostname not in ('127.0.0.1','localhost','::1') or parsed.username or parsed.password:
            raise ValueError('Use a loopback WebUI URL on the server; do not send the admin token to external hosts')
        if not token:
            raise ValueError('WEBUI_ADMIN_TOKEN is required')
        self.base_url = base_url.rstrip('/')
        self.token = token

    def request(self, method, suffix='', body=None):
        payload = json.dumps(body).encode() if body is not None else None
        request = Request(self.base_url+'/api/v1/tools/id/'+TOOL_ID+suffix, data=payload, method=method, headers={'Authorization':'Bearer '+self.token,'Content-Type':'application/json'})
        # A redirect must never forward an admin token to another host.
        import urllib.request
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None
        with urllib.request.build_opener(NoRedirect).open(request,timeout=30) as response:
            return json.load(response)


def form(snapshot, source):
    for field in ('id','name','content','meta','access_grants'):
        if field not in snapshot:
            raise ValueError('Tool export must include source, metadata and access grants')
    if snapshot['id'] != TOOL_ID:
        raise ValueError('Unexpected tool ID')
    compile(source, '<candidate-gateway>', 'exec')
    return {key:(source if key=='content' else snapshot[key]) for key in ('id','name','content','meta','access_grants')}


def inspect_current(api, expected_sha):
    current = api.request('GET')
    if digest(current.get('content','')) != expected_sha:
        raise ValueError('Installed source changed; stop and refresh the owner-reviewed baseline')
    form(current,current['content'])
    return current


def verify_readback(current, expected_source, baseline, required_methods):
    if digest(current.get('content','')) != digest(expected_source):
        raise ValueError('Source readback mismatch; do not claim deployed')
    specs = {s.get('name') for s in current.get('specs',[]) if isinstance(s,dict)}
    if not required_methods.issubset(specs):
        raise ValueError('Installed method schemas missing; deployment acceptance failed')
    if current.get('access_grants') != baseline.get('access_grants'):
        raise ValueError('Tool access grants changed; deployment acceptance failed')


def apply(api, source, expected_sha, backup_path, owner_lease):
    if not owner_lease:
        raise ValueError('Exclusive Engineering owner lease is required')
    baseline = inspect_current(api, expected_sha)
    payload = form(baseline, source)
    backup = {'baseline':baseline,'candidate_sha256':digest(source),'owner_lease':owner_lease}
    fd = os.open(backup_path, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
    with os.fdopen(fd,'w') as handle:
        json.dump(backup,handle);handle.flush();os.fsync(handle.fileno())
    inspect_current(api, expected_sha)  # Refuse intervening edits immediately before POST.
    response_lost = False
    try:
        api.request('POST','/update',payload)  # Exactly one update attempt.
    except Exception:
        response_lost = True  # Resolve by readback, never by replaying the write.
    readback = api.request('GET')
    verify_readback(readback,source,baseline,METHODS)
    return {'status':'API_SOURCE_AND_SCHEMA_VERIFIED','candidate_sha256':digest(source),'write_response_lost':response_lost,'broker_requests':0,'runtime_trading_acceptance':'PENDING'}


def rollback(api, backup_path, owner_lease):
    if not owner_lease:
        raise ValueError('Exclusive Engineering owner lease is required')
    backup = json.loads(Path(backup_path).read_text())
    baseline = backup['baseline']
    inspect_current(api,backup['candidate_sha256'])  # Never overwrite another owner's newer source.
    payload=form(baseline,baseline['content'])
    response_lost=False
    try:
        api.request('POST','/update',payload)
    except Exception:
        response_lost=True
    required={s.get('name') for s in baseline.get('specs',[]) if isinstance(s,dict)}
    verify_readback(api.request('GET'),baseline['content'],baseline,required)
    return {'status':'ROLLBACK_SOURCE_AND_SCHEMA_VERIFIED','write_response_lost':response_lost,'broker_requests':0}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',required=True)
    parser.add_argument('--expected-sha')
    parser.add_argument('--source',type=Path,default=Path(__file__).resolve().parents[1]/'openwebui/tools/trading212_demo_gateway_v03_selfcontained.py')
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--apply',action='store_true')
    mode.add_argument('--rollback',type=Path)
    parser.add_argument('--backup',type=Path)
    parser.add_argument('--owner-lease',default='')
    args=parser.parse_args()
    api=API(args.url,os.getenv('WEBUI_ADMIN_TOKEN',''))
    if args.rollback:
        result=rollback(api,args.rollback,args.owner_lease)
    else:
        if not args.expected_sha:
            parser.error('--expected-sha is required')
        source=args.source.read_text()
        if args.apply:
            if not args.backup:parser.error('--backup is required for --apply')
            result=apply(api,source,args.expected_sha,args.backup,args.owner_lease)
        else:
            baseline=inspect_current(api,args.expected_sha)
            form(baseline,source)
            result={'status':'PREFLIGHT_ONLY','candidate_sha256':digest(source),'production_writes':0,'broker_requests':0}
    print(json.dumps(result,sort_keys=True))


if __name__=='__main__':
    main()

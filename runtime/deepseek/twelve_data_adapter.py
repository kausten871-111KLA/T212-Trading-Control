"""Twelve Data host-side global market research adapter, no brokerage execution.

Provider docs (2026-10): /quote and /time_series 1 credit/symbol,
 /symbol_search 1 credit/request, /api_usage 1 credit/request.
No market_movers (100 credits, Pro+), cross (5 credits), or paid data defaults.
Only approved authenticated callers via the existing Contabo bridge may reach
this adapter. Secrets stay in a private host-only file and an HTTP auth header.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import re
import sqlite3
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

KEY_FILE = Path.home() / ".config/deepseek-runtime/data-api.env"
DB_FILE = Path.home() / ".local/state/deepseek-runtime/twelve_data_cache.sqlite3"
BASE_URL = "https://api.twelvedata.com"
SYMBOL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/^+-]{0,30}\Z")
SEARCH_TERM = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._/-]{0,63}\Z")
EXCHANGE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,39}\Z")
INTERVALS = frozenset({"1min", "5min", "15min", "30min", "1h", "1day", "1week"})
ENDPOINTS = {
    "quote": ("quote", 1, 30),
    "time_series": ("time_series", 1, 90),
    "symbol_search": ("symbol_search", 1, 86400),
    "api_usage": ("api_usage", 1, 60),
}
# The Basic plan currently advertises 8 credits/min and 800/day. Staying
# below that permits the user to allocate spare quota to other clients.
# These are DATA SPEND guards only, never trading-risk or DEMO restrictions.
MAX_LOCAL_PER_MINUTE = 6
MAX_LOCAL_PER_DAY = 600
MAX_RESPONSE_BYTES = 220_000


def _key(path: Path = KEY_FILE):
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("TWELVEDATA_API_KEY="):
            key = line.partition("=")[2].strip().strip("\"'")
            if re.fullmatch(r"[A-Za-z0-9_-]{8,256}", key):
                return key
            return None
    return None


def _validate_identifier(value, pattern, name, *, required=True):
    if value is None or value == "":
        if not required:
            return None
        raise ValueError("invalid_" + name)
    if not isinstance(value, str) or not pattern.fullmatch(value.strip()):
        raise ValueError("invalid_" + name)
    return value.strip().upper()


def _db(path):
    p=Path(path)
    p.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    os.chmod(p.parent,0o700)
    conn=sqlite3.connect(str(p),timeout=15,isolation_level=None)
    if p.exists():
        os.chmod(p,0o600)
    conn.execute("CREATE TABLE IF NOT EXISTS quota (bucket TEXT PRIMARY KEY, credits INTEGER NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS cache (request_hash TEXT PRIMARY KEY, fetched_at INTEGER NOT NULL, response_json TEXT NOT NULL)")
    return conn


def _cred_safe_result(kind, symbol, resp, headers, now):
    provider_status = resp.get("status") if isinstance(resp,dict) else None
    if not isinstance(resp,dict):
        return {"ok":False,"error":"provider_invalid_json","provider":"Twelve Data"}
    if provider_status == "error" or "code" in resp and "message" in resp:
        code=resp.get("code")
        return {
            "ok":False,"error":"provider_rejected_request",
            "provider":"Twelve Data","http_provider_code":code if isinstance(code,int) else None,
            "entitlement_or_plan_may_be_required":code in (401,403),
            "rate_limit_reached":code==429,
        }
    common={
        "ok":True,"provider":"Twelve Data","endpoint":kind,
        "fetched_at_utc":datetime.fromtimestamp(now,timezone.utc).isoformat(),
        "provider_live_market_data_unverified":True,
        "execution_quote":False,
    }
    if symbol:common["requested_symbol"]=symbol
    if kind == "quote":
        if resp.get("symbol") and resp["symbol"].upper()!=symbol:
            return {"ok":False,"error":"provider_symbol_mismatch","provider":"Twelve Data"}
        common.update({
            "symbol":resp.get("symbol",symbol),
            "name":resp.get("name"), "exchange":resp.get("exchange"),
            "mic_code":resp.get("mic_code"),"currency":resp.get("currency"),
            "exchange_timezone":resp.get("exchange_timezone"),
            "datetime":resp.get("datetime"),"timestamp":resp.get("timestamp"),
            "is_market_open":resp.get("is_market_open"),
            "close":resp.get("close"),"previous_close":resp.get("previous_close"),
            "change_percent":resp.get("percent_change"),
            "open":resp.get("open"),"high":resp.get("high"),"low":resp.get("low"),
            "volume":resp.get("volume"),
            "bid":resp.get("bid"),"ask":resp.get("ask"),
        })
        common["quote_timestamp_independently_attested"]=False
    elif kind == "time_series":
        meta=resp.get("meta")
        values=resp.get("values")
        if not isinstance(meta,dict) or not isinstance(values,list):
            return {"ok":False,"error":"provider_missing_series","provider":"Twelve Data"}
        actual=meta.get("symbol")
        if actual and str(actual).upper()!=symbol:
            return {"ok":False,"error":"provider_symbol_mismatch","provider":"Twelve Data"}
        common["meta"]={k:meta.get(k) for k in
            ("symbol","interval","currency","exchange_timezone","exchange","mic_code","type")}
        common["values"]=[{k:v.get(k) for k in ("datetime","open","high","low","close","volume")}
                          for v in values[:100] if isinstance(v,dict)]
        common["bar_time_basis"]=(
            "exchange_local_date" if meta.get("interval") in ("1day","1week") else
            "UTC_requested_provider_series"
        )
        common["bar_prices_are_not_executable_quotes"]=True
    elif kind == "symbol_search":
        data=resp.get("data")
        if not isinstance(data,list):
            return {"ok":False,"error":"provider_missing_search_data","provider":"Twelve Data"}
        common["matches"]=[{k:v.get(k) for k in
                ("symbol","instrument_name","exchange","mic_code","exchange_timezone","instrument_type","country","currency")}
                for v in data[:30] if isinstance(v,dict)]
        common["match_count"]=len(common["matches"])
    elif kind == "api_usage":
        # Provider usage response, excluding anything resembling credentials.
        safe_keys=("plan","timestamp","current_usage","plan_limit","credits_used","credits_left",
                   "api_credits","minute_limit","daily_limit")
        common["usage"]={k:resp.get(k) for k in safe_keys if k in resp}
    credits={}
    for header in ("api-credits-used","api-credits-left"):
        raw=headers.get(header) if hasattr(headers,"get") else None
        try:
            if raw is not None:credits[header]=int(raw)
        except (TypeError,ValueError):pass
    if credits:common["provider_credits"]=credits
    return common


def query(kind, symbol="AAPL", *, exchange=None, mic_code=None,
          interval="1day", outputsize=30, key_file=KEY_FILE,
          db_file=DB_FILE, fetch=urlopen, clock=time.time):
    """One quota-reserved provider GET or cached result.

    No retries: every real request may incur a credit. All provider errors
    are normalised with no exception string that could contain a secret.
    """
    if kind not in ENDPOINTS:
        return {"ok":False,"error":"unknown_twelve_data_operation"}
    try:
        sym=None if kind=="api_usage" else _validate_identifier(
            symbol,SEARCH_TERM if kind=="symbol_search" else SYMBOL,"symbol")
        exch=_validate_identifier(exchange,EXCHANGE,"exchange",required=False)
        mic=_validate_identifier(mic_code,EXCHANGE,"mic_code",required=False)
        if interval not in INTERVALS:
            return {"ok":False,"error":"invalid_interval","supported":sorted(INTERVALS)}
        if isinstance(outputsize,bool) or not isinstance(outputsize,int) or not 1<=outputsize<=100:
            return {"ok":False,"error":"invalid_outputsize"}
        if kind=="api_usage" and (exch or mic):
            return {"ok":False,"error":"invalid_usage_parameters"}
    except ValueError as e:
        return {"ok":False,"error":str(e)}
    key=_key(Path(key_file))
    if not key:
        return {"ok":False,"error":"twelve_data_key_not_configured",
                "provider":"Twelve Data"}
    route,weight,ttl=ENDPOINTS[kind]
    params={}
    if kind!="api_usage":
        params["symbol"]=sym
    if kind in ("quote","time_series") and exch:params["exchange"]=exch
    if kind in ("quote","time_series") and mic:params["mic_code"]=mic
    if kind=="time_series":
        params.update(interval=interval,outputsize=outputsize,order="desc")
        if interval not in ("1day","1week"):params["timezone"]="UTC"
    query_string=urlencode(params)
    cache_input=json.dumps([route,sorted(params.items())],separators=(",",":"))
    cache_hash=hashlib.sha256(cache_input.encode()).hexdigest()
    now=int(clock())
    minute=datetime.fromtimestamp(now,timezone.utc).strftime("%Y%m%d%H%M")
    day=datetime.fromtimestamp(now,timezone.utc).strftime("%Y%m%d")
    with _db(db_file) as db:
        db.execute("BEGIN IMMEDIATE")
        hit=db.execute("SELECT fetched_at,response_json FROM cache WHERE request_hash=?",(cache_hash,)).fetchone()
        if hit and 0 <= now-hit[0] < ttl:
            db.execute("COMMIT")
            result=json.loads(hit[1])
            return {**result,"cached":True,"cache_age_seconds":now-hit[0]}
        bucket_minute="m:"+minute
        bucket_day="d:"+day
        used_minute=db.execute("SELECT credits FROM quota WHERE bucket=?",(bucket_minute,)).fetchone()
        used_day=db.execute("SELECT credits FROM quota WHERE bucket=?",(bucket_day,)).fetchone()
        if (used_minute and used_minute[0]+weight>MAX_LOCAL_PER_MINUTE) or (
            used_day and used_day[0]+weight>MAX_LOCAL_PER_DAY):
            db.execute("COMMIT")
            return {"ok":False,"provider":"Twelve Data",
                    "error":"local_twelve_data_credit_budget_exhausted",
                    "credit_weight":weight,
                    "minute_budget":MAX_LOCAL_PER_MINUTE,
                    "day_budget":MAX_LOCAL_PER_DAY}
        for bucket in (bucket_minute,bucket_day):
            db.execute(
                "INSERT INTO quota(bucket,credits) VALUES(?,?) "
                "ON CONFLICT(bucket) DO UPDATE SET credits=credits+excluded.credits",
                (bucket,weight))
        db.execute("COMMIT")
    request=Request(BASE_URL+"/"+route+("?"+query_string if query_string else ""),
                    headers={"Authorization":"apikey "+key,
                             "Accept":"application/json",
                             "User-Agent":"TradingBrainData/1.0"},
                    method="GET")
    try:
        with fetch(request,timeout=12) as result:
            raw=result.read(MAX_RESPONSE_BYTES+1)
            if len(raw)>MAX_RESPONSE_BYTES:
                return {"ok":False,"error":"provider_response_too_large","provider":"Twelve Data"}
            response=json.loads(raw.decode("utf-8"))
            headers=result.headers
    except HTTPError as error:
        return {"ok":False,"error":"provider_http_error",
                "provider":"Twelve Data","http_status":error.code,
                "entitlement_or_plan_may_be_required":error.code==403,
                "rate_limit_reached":error.code==429}
    except (URLError,TimeoutError,OSError,ValueError,UnicodeDecodeError) as error:
        return {"ok":False,"error":"provider_connection_or_format_error",
                "provider":"Twelve Data","error_type":type(error).__name__}
    parsed=_cred_safe_result(kind,sym,response,headers,now)
    parsed["cached"]=False
    parsed["credit_weight_estimate"]=weight
    # Cache only successful provider results; errors may be transient or plan-related.
    if parsed.get("ok"):
        with _db(db_file) as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT INTO cache(request_hash,fetched_at,response_json) VALUES (?,?,?) "
                       "ON CONFLICT(request_hash) DO UPDATE SET fetched_at=excluded.fetched_at,"
                       "response_json=excluded.response_json",
                       (cache_hash,now,json.dumps(parsed,separators=(",",":"),ensure_ascii=False)))
            db.execute("COMMIT")
    return parsed

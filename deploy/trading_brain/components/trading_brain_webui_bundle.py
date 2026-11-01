"""
title: Trading Brain Research Context
author: Trading Operations Engineering
description: Additive evidence, quote economics, market momentum, and optional prior research context. Never submits orders or changes broker settings.
version: 0.1.0
"""
from __future__ import annotations


# ========== quote_economics.py ==========


"""Research-only quote/spread economics from frozen observations.

Never treats a quote as executable and never prescribes a trade cutoff.
No Trading 212 credentials or order API.
"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

def _positive_number(value, name):
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(name + ' must be numeric')
    try:
        number = Decimal(str(value))
    except (ValueError, InvalidOperation) as exc:
        raise ValueError(name + ' not numeric') from exc
    if not number.is_finite() or number <= 0:
        raise ValueError(name + ' must be positive and finite')
    return number

def quote_economics(row, *, quantity=1, fee_per_side=0, slippage_each_side=0):
    """Worst-case immediate buy at ask, sell at bid, optional costs.

    Numbers in quote currency. Slippage is a scenario input, not verified data.
    Returns null costs where no complete valid bid/ask pair exists.
    """
    ticker = str(row.get('ticker') or '').strip()
    if not ticker:
        raise ValueError('ticker required')
    qty = _positive_number(quantity, 'quantity')
    fee = Decimal(str(fee_per_side))
    slippage = Decimal(str(slippage_each_side))
    if any((not x.is_finite() or x < 0 for x in (fee, slippage))):
        raise ValueError('Fees and slippage must be non-negative finite')
    bid = _positive_number(row.get('bid'), 'bid')
    ask = _positive_number(row.get('ask'), 'ask')
    if (bid is None) != (ask is None):
        raise ValueError('incomplete bid/ask pair')
    base = {'ticker': ticker, 'observation_only': True, 'quote_time_utc': row.get('quote_time_utc'), 'freshness_verified': False, 'scenario_quantity': str(qty), 'bid': str(bid) if bid is not None else None, 'ask': str(ask) if ask is not None else None, 'roundtrip_spread_cost': None, 'roundtrip_total_cost': None, 'spread_pct_mid': None, 'quote_status': 'MISSING_QUOTE' if bid is None else 'OBSERVED_NOT_EXECUTABLE'}
    if bid is None:
        return base
    if bid > ask:
        raise ValueError('crossed bid/ask')
    mid = (bid + ask) / 2
    spread_cost = (ask - bid) * qty
    scenario = spread_cost + (fee + slippage) * 2
    base.update({'spread_pct_mid': float((ask - bid) / mid * 100), 'roundtrip_spread_cost': str(spread_cost), 'roundtrip_total_cost': str(scenario), 'quote_status': 'OBSERVED_NOT_EXECUTABLE'})
    return base

def quote_audit(rows, **scenario):
    return [quote_economics(row, **scenario) for row in rows]


# ========== momentum_features.py ==========


"""Timestamped research-only bar calculations (not broker execution signals)."""
from datetime import datetime, timezone
import math

def _timestamp(value):
    if not isinstance(value, str):
        raise ValueError('UTC timestamp required')
    t = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if t.tzinfo is None:
        raise ValueError('naive timestamp')
    return t.astimezone(timezone.utc)

def _float(v, name):
    if isinstance(v, bool) or v is None:
        raise ValueError(name + ' numeric required')
    try:
        n = float(v)
    except (TypeError, ValueError) as e:
        raise ValueError(name + ' invalid') from e
    if not math.isfinite(n):
        raise ValueError(name + ' invalid')
    return n

def analyse_bars(bars, *, as_of_utc, average_daily_volume=None):
    """Compute price return, available period VWAP and conditional RVOL.

    Bar timestamps must be distinct, sorted and no later than the cutoff.
    RVOL needs a supplied historical comparable-volume baseline. Never
    substitutes absolute volume or an arbitrary reference for RVOL.
    """
    cutoff = _timestamp(as_of_utc)
    prev = None
    seen = []
    for r in bars:
        t = _timestamp(r['timestamp_utc'])
        if t > cutoff:
            raise ValueError('future bar violates point-in-time boundary')
        if prev is not None and t <= prev:
            raise ValueError('bars must be strictly ascending')
        prev = t
        close = _float(r['close'], 'close')
        volume = _float(r['volume'], 'volume')
        if close <= 0 or volume < 0:
            raise ValueError('invalid close or volume')
        high = _float(r.get('high', close), 'high')
        low = _float(r.get('low', close), 'low')
        if low <= 0 or low > close or close > high:
            raise ValueError('invalid high/low/close')
        seen.append((t, close, volume, high, low))
    out = {'as_of_utc': cutoff.isoformat(), 'bars': len(seen), 'first_bar_utc': seen[0][0].isoformat() if seen else None, 'last_bar_utc': seen[-1][0].isoformat() if seen else None, 'momentum_return_pct': None, 'volume_weighted_price': None, 'relative_volume': None, 'missing_inputs': [], 'not_an_executable_quote': True}
    if len(seen) >= 2:
        out['momentum_return_pct'] = (seen[-1][1] / seen[0][1] - 1) * 100
    else:
        out['missing_inputs'].append('At least two timestamped bars')
    total = sum((x[2] for x in seen))
    if total > 0:
        out['volume_weighted_price'] = sum(((x[3] + x[4] + x[1]) / 3 * x[2] for x in seen)) / total
    else:
        out['missing_inputs'].append('Non-zero volume for VWAP proxy')
    if average_daily_volume is None:
        out['missing_inputs'].append('Historical comparable-volume baseline for RVOL')
    else:
        av = _float(average_daily_volume, 'average_daily_volume')
        if av <= 0:
            raise ValueError('baseline volume must be positive')
        if seen:
            out['relative_volume'] = total / av
        else:
            out['missing_inputs'].append('Observed volume for RVOL')
    return out


# ========== finmem_research.py ==========


"""FinMem-inspired offline research memory with point-in-time retrieval.

Independent research DB; NEVER opens the live controller's trading_state.db.
Decision evidence is immutable; outcomes are appended separately after they
become known. An evaluation query cannot see information from the future.
"""
from datetime import datetime, timezone
import sqlite3
from pathlib import Path
DDL = '\nCREATE TABLE IF NOT EXISTS research_decision (\n decision_id TEXT PRIMARY KEY,\n ticker TEXT NOT NULL,\n observed_at_utc TEXT NOT NULL,\n phase TEXT NOT NULL,\n thesis TEXT NOT NULL,\n evidence_sha256 TEXT NOT NULL\n);\nCREATE TABLE IF NOT EXISTS research_outcome (\n decision_id TEXT PRIMARY KEY,\n known_at_utc TEXT NOT NULL,\n label TEXT NOT NULL,\n observation TEXT NOT NULL,\n FOREIGN KEY(decision_id) REFERENCES research_decision(decision_id)\n);\nCREATE TABLE IF NOT EXISTS research_reflection (\n reflection_id TEXT PRIMARY KEY,\n decision_id TEXT NOT NULL,\n known_at_utc TEXT NOT NULL,\n lesson TEXT NOT NULL,\n FOREIGN KEY(decision_id) REFERENCES research_decision(decision_id)\n);\n'

def _dt(value):
    if not isinstance(value, str):
        raise ValueError('timestamp required')
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('timezone required')
    return stamp.astimezone(timezone.utc)

def connect(path):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(p))
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.executescript(DDL)
    return db

def record_decision(db, *, decision_id, ticker, observed_at_utc, phase, thesis, evidence_sha256):
    t = _dt(observed_at_utc).isoformat()
    if not all((isinstance(x, str) and x.strip() for x in (decision_id, ticker, phase, thesis, evidence_sha256))):
        raise ValueError('invalid decision fields')
    if len(evidence_sha256) != 64 or any((x not in '0123456789abcdef' for x in evidence_sha256)):
        raise ValueError('invalid evidence SHA256')
    with db:
        db.execute('INSERT INTO research_decision VALUES(?,?,?,?,?,?)', (decision_id, ticker.upper(), t, phase, thesis, evidence_sha256))
    return decision_id

def add_outcome(db, *, decision_id, known_at_utc, label, observation):
    when = _dt(known_at_utc)
    r = db.execute('SELECT observed_at_utc FROM research_decision WHERE decision_id=?', (decision_id,)).fetchone()
    if not r:
        raise ValueError('unknown decision')
    if when < _dt(r['observed_at_utc']):
        raise ValueError('outcome predates decision')
    if not label or not observation:
        raise ValueError('outcome needs evidence')
    with db:
        db.execute('INSERT INTO research_outcome VALUES(?,?,?,?)', (decision_id, when.isoformat(), label, observation))

def add_reflection(db, *, reflection_id, decision_id, known_at_utc, lesson):
    when = _dt(known_at_utc)
    prior = db.execute('SELECT observed_at_utc FROM research_decision WHERE decision_id=?', (decision_id,)).fetchone()
    if not prior or when < _dt(prior['observed_at_utc']):
        raise ValueError('unknown or future decision')
    if not reflection_id or not lesson:
        raise ValueError('reflection needs ID and lesson')
    with db:
        db.execute('INSERT INTO research_reflection VALUES(?,?,?,?)', (reflection_id, decision_id, when.isoformat(), lesson))

def _tier(age_hours):
    if age_hours < 24:
        return 'short'
    if age_hours < 14 * 24:
        return 'medium'
    return 'long'

def retrieve(db, *, as_of_utc, ticker=None, phase=None, limit=25):
    """Return ONLY information available by as_of; never silently insert outcomes."""
    cutoff = _dt(as_of_utc)
    if not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError('1..100 results required')
    query = 'SELECT * FROM research_decision WHERE observed_at_utc<=?'
    params = [cutoff.isoformat()]
    if ticker:
        query += ' AND ticker=?'
        params.append(ticker.upper())
    if phase:
        query += ' AND phase=?'
        params.append(phase)
    query += ' ORDER BY observed_at_utc DESC, decision_id ASC LIMIT ?'
    params.append(limit)
    out = []
    for row in db.execute(query, params):
        observed = _dt(row['observed_at_utc'])
        hours = (cutoff - observed).total_seconds() / 3600
        outcome = db.execute('SELECT known_at_utc,label,observation FROM research_outcome WHERE decision_id=? AND known_at_utc<=?', (row['decision_id'], cutoff.isoformat())).fetchone()
        reflections = db.execute('SELECT reflection_id,known_at_utc,lesson FROM research_reflection WHERE decision_id=? AND known_at_utc<=? ORDER BY known_at_utc', (row['decision_id'], cutoff.isoformat())).fetchall()
        out.append({'decision_id': row['decision_id'], 'ticker': row['ticker'], 'phase': row['phase'], 'observed_at_utc': row['observed_at_utc'], 'thesis': row['thesis'], 'evidence_sha256': row['evidence_sha256'], 'memory_tier': _tier(hours), 'outcome': dict(outcome) if outcome else None, 'reflections': [dict(x) for x in reflections]})
    return out


# ========== evidence_review.py ==========


"""Advisory evidence-quality annotations for saved research-role outputs.

Never blocks, routes or executes an order and never mutates original decisions.
All cited catalyst text must be separately verified before considered a fact.
"""
import re

def assess_decision(row, observation):
    ticker = row.get('ticker')
    if ticker != observation.get('ticker'):
        raise ValueError('decision/evidence mismatch')
    reasons = []
    fields = ['price', 'bid', 'ask', 'exchange', 'vwap', 'rvol']
    for name in fields:
        if observation.get(name) is None:
            reasons.append('missing_' + name)
    if observation.get('stale'):
        reasons.append('stale_observation')
    spread = observation.get('spread_pct')
    if spread is not None:
        reasons.append('reported_spread_pct_' + format(float(spread), '.2f'))
    remarks = '\n'.join((str(row.get(k) or '') for k in ('thesis', 'bull_case', 'bear_case')))
    signatures = {'institutional_activity_claim': '\\binstitutional (interest|buying|demand)\\b', 'unverified_catalyst_claim': '\\b(FDA|clinical data|merger rumours?|M&A rumors?)\\b', 'news_absence_claim': '\\b(no negative news|absence of negative news)\\b', 'unsupported_intraday_claim': '\\b(sustained intraday|intraday surge|confirmed intraday)\\b', 'spread_description': '\\b(narrow spread|tight spread|relatively narrow)\\b'}
    for label, pattern in signatures.items():
        if re.search(pattern, remarks, flags=re.IGNORECASE):
            reasons.append('review_' + label)
    return {'ticker': ticker, 'action': row.get('action'), 'quote_verified': False, 'catalyst_verified': False, 'flags': sorted(set(reasons)), 'research_only': True, 'action_changed': False}

def review_fixture(evidence, decisions):
    by_ticker = {r['ticker']: r for r in evidence['candidates']}
    if len(by_ticker) != len(evidence['candidates']):
        raise ValueError('duplicate evidence tickers')
    seen = set()
    out = []
    for r in decisions:
        name = r.get('ticker')
        if name not in by_ticker or name in seen:
            raise ValueError('unsupported or duplicate decision ticker')
        seen.add(name)
        out.append(assess_decision(r, by_ticker[name]))
    return out


# ========== market_gateway_normalizer.py ==========


"""Adapt actual market_data_gateway snapshots/bars without invented fields.

The existing Open WebUI Alpaca gateway returns:
  snapshots: {"provider":"Alpaca","feed":"iex","readOnly":true,
              "symbols":[{"symbol":"MYGN","price":..,"bid":..,...}]}
  bars: {"bars":{"MYGN":[{"t":ISO8601,"o":..,"h":..,"l":..,"c":..,"v":..}]}}

Capturing time is user-provided, not a provider-signed timestamp. The output
marks this explicitly and carries original vendor quote/trade timestamps.
"""
from datetime import datetime, timezone
from typing import Any

def _normal_time(value: str) -> str:
    if not isinstance(value, str) or len(value) > 50:
        raise ValueError('Timezone-aware observation time required')
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError('Invalid observation time') from exc
    if result.tzinfo is None:
        raise ValueError('Timezone required')
    return result.astimezone(timezone.utc).isoformat()

def _symbol(value: str):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Ticker required')
    return value.strip().upper()

def normalise_snapshot(data: dict, *, ticker: str, as_of_utc: str) -> dict:
    """Accept either the research fixture format or *actual* Alpaca gateway JSON."""
    if not isinstance(data, dict):
        raise ValueError('Market snapshot must be JSON object')
    if 'candidates' in data or 'observation' in data:
        return data
    if data.get('provider') != 'Alpaca' or data.get('readOnly') is not True:
        raise ValueError('Unsupported market data source')
    if data.get('feed') not in ('iex', 'sip', 'delayed_sip', 'boats', 'overnight', 'otc'):
        raise ValueError('Missing recognised feed')
    symbols = data.get('symbols')
    if not isinstance(symbols, list) or len(symbols) > 30:
        raise ValueError('Malformed market-data gateway symbols')
    symbol = _symbol(ticker)
    hits = [row for row in symbols if isinstance(row, dict) and str(row.get('symbol') or '').upper() == symbol]
    if len(hits) != 1:
        raise ValueError('Requested ticker not unique in snapshot')
    r = hits[0]
    observed = _normal_time(as_of_utc)
    return {'dataset_id': 'alpaca-gateway-' + data['feed'] + '-' + symbol + '-' + observed, 'observation_timestamp_utc': observed, 'market_state': 'not independently verified', 'data_source': 'Alpaca ' + data['feed'] + ' through existing WebUI gateway; research input', 'source_capture_time_supplied_by_caller': True, 'source_raw_receipt_independently_verified': False, 'observation': {'ticker': symbol, 'price': r.get('price'), 'change_pct': r.get('changePctVsPrevClose'), 'day_volume': r.get('dayVolume'), 'bid': r.get('bid'), 'ask': r.get('ask'), 'spread_pct': r.get('spreadPct'), 'exchange': None, 'vwap': None, 'rvol': None, 'catalyst': None, 'stale': None, 'quote_time_utc': r.get('quoteTimestamp'), 'trade_time_utc': r.get('tradeTimestamp'), 'source': 'Alpaca ' + data['feed'] + ' gateway output', 'source_tier': 'gateway_result_not_independently_attested'}}

def normalise_bars(data: Any, *, ticker: str) -> list[dict]:
    """Accept an already-normalised list or the Alpaca /v2/stocks/bars payload."""
    if isinstance(data, list):
        return data
    if not isinstance(data, dict) or not isinstance(data.get('bars'), dict):
        raise ValueError('Bars must be a list or Alpaca bar response')
    symbol = _symbol(ticker)
    bar_rows = data['bars'].get(symbol)
    if not isinstance(bar_rows, list):
        raise ValueError('Bars response missing requested symbol')
    if len(bar_rows) > 800:
        raise ValueError('Bar list exceeds research bound')
    out = []
    for bar in bar_rows:
        if not isinstance(bar, dict):
            raise ValueError('Invalid bar record')
        out.append({'timestamp_utc': bar.get('t'), 'close': bar.get('c'), 'volume': bar.get('v'), 'high': bar.get('h'), 'low': bar.get('l')})
    return out


# ========== research_context.py ==========


"""Trading Brain research context: a single, broker-neutral evidence envelope.

Consumes external observations supplied by an existing market-data tool;
never downloads data, calls a model, places an order, or changes decisions.
Memory is point-in-time and may only contain previously observed decisions.
"""
from datetime import datetime, timezone
import hashlib
import json
import math
import re
from typing import Any
SYMBOL = re.compile('[A-Z0-9][A-Z0-9._^-]{0,20}\\Z')
ALLOWED_FIELDS = ('ticker', 'price', 'change_pct', 'day_volume', 'bid', 'ask', 'spread_pct', 'exchange', 'vwap', 'rvol', 'catalyst', 'stale', 'quote_time_utc', 'trade_time_utc', 'source', 'source_tier')
MAX_BARS = 800
MAX_MEMORIES = 20

def _iso_utc(value: str) -> str:
    if not isinstance(value, str) or len(value) > 50:
        raise ValueError('Explicit bounded timestamp required')
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError('Invalid timestamp') from exc
    if result.tzinfo is None:
        raise ValueError('Timezone required')
    return result.astimezone(timezone.utc).isoformat()

def _finite(value: Any, *, allow_none=True):
    if value is None and allow_none:
        return None
    if isinstance(value, bool):
        raise ValueError('Boolean is not a price or quantity')
    try:
        v = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError('Invalid numeric market field') from exc
    if not math.isfinite(v):
        raise ValueError('Non-finite market data')
    return v

def _lookup(data: dict, ticker: str) -> dict:
    if 'candidates' in data:
        entries = data['candidates']
        if not isinstance(entries, list) or not 0 < len(entries) <= 100:
            raise ValueError('Invalid candidate list size')
        matches = [x for x in entries if isinstance(x, dict) and x.get('ticker') == ticker]
        if len(matches) != 1:
            raise ValueError('Ticker must occur exactly once in supplied dataset')
        return matches[0]
    row = data.get('observation')
    if not isinstance(row, dict) or row.get('ticker') != ticker:
        raise ValueError('Ticker mismatch')
    return row

def compile_context(data: dict, *, ticker: str, as_of_utc: str, decision: dict | None=None, bars: list[dict] | None=None, average_daily_volume: float | None=None, memory_db=None, quantity: int=100) -> dict:
    """Create a deterministic, evidence-first research context packet.

    The input snapshot's capture time, not its content labels, establishes
    the earliest credible availability. A subsequent live quote must carry
    its own timestamp before its freshness can be verified.
    """
    if not isinstance(data, dict):
        raise ValueError('A structured snapshot is required')
    sym = ticker.strip().upper() if isinstance(ticker, str) else ''
    if not SYMBOL.fullmatch(sym):
        raise ValueError('Invalid ticker')
    now = _iso_utc(as_of_utc)
    observed = _iso_utc(data.get('observation_timestamp_utc'))
    if observed > now:
        raise ValueError('Future snapshot cannot be used')
    row = _lookup(data, sym)
    for name in ('price', 'change_pct', 'day_volume', 'bid', 'ask', 'spread_pct', 'vwap', 'rvol'):
        _finite(row.get(name))
    if row.get('day_volume') is not None and _finite(row['day_volume']) < 0:
        raise ValueError('Negative day volume')
    quote_ts = row.get('quote_time_utc')
    if quote_ts is not None:
        quote_ts = _iso_utc(quote_ts)
        if quote_ts > now:
            raise ValueError('Future quote timestamp')
    trade_ts = row.get('trade_time_utc')
    if trade_ts is not None:
        trade_ts = _iso_utc(trade_ts)
        if trade_ts > now:
            raise ValueError('Future trade timestamp')
    factual = {key: row.get(key) for key in ALLOWED_FIELDS}
    factual['ticker'] = sym
    factual['quote_time_utc'] = quote_ts
    factual['trade_time_utc'] = trade_ts
    factual['catalyst'] = None
    source = str(data.get('data_source') or 'UNSPECIFIED')[:300]
    observed_hypothesis = row.get('catalyst')
    if not isinstance(observed_hypothesis, str):
        observed_hypothesis = None
    if observed_hypothesis:
        observed_hypothesis = observed_hypothesis[:450]
    evidence = {'dataset_id': str(data.get('dataset_id') or 'unspecified')[:150], 'ticker': sym, 'market_observation_time_utc': observed, 'as_of_utc': now, 'data_source_claim': source, 'observation_time_is_caller_supplied': bool(data.get('source_capture_time_supplied_by_caller')), 'source_raw_receipt_independently_verified': False, 'observation': factual}
    digest = hashlib.sha256(json.dumps(evidence, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')).hexdigest()
    quote = quote_economics({'ticker': sym, 'bid': row.get('bid'), 'ask': row.get('ask'), 'quote_time_utc': quote_ts}, quantity=quantity)
    bars = [] if bars is None else bars
    if not isinstance(bars, list) or len(bars) > MAX_BARS:
        raise ValueError('Invalid bar count')
    bar_analysis = analyse_bars(bars, as_of_utc=now, average_daily_volume=average_daily_volume)
    memory = retrieve(memory_db, as_of_utc=now, ticker=sym, limit=MAX_MEMORIES) if memory_db is not None else []
    audit = assess_decision(decision, row) if decision is not None else None
    source_missing = [key for key in ('exchange', 'price', 'bid', 'ask', 'rvol', 'vwap') if row.get(key) is None]
    if data.get('source_capture_time_supplied_by_caller'):
        source_missing.append('provider_attested_snapshot_capture_time')
    if not quote_ts:
        source_missing.append('timestamped_bid_ask_quote')
    if not trade_ts:
        source_missing.append('timestamped_last_trade')
    if observed_hypothesis and observed_hypothesis.lower() not in ('unknown', 'none'):
        source_missing.append('independent_primary_catalyst_source')
    output = {'schema_version': 1, 'research_only': True, 'broker_order_instructions': False, 'decision_action_changed': False, 'ticker': sym, 'as_of_utc': now, 'evidence_sha256': digest, 'source_evidence': evidence, 'catalyst_hypothesis_unverified': observed_hypothesis, 'quote_economics_hypothetical': quote, 'bar_features': bar_analysis, 'history_as_of': memory, 'decision_quality_advisory': audit, 'missing_evidence': sorted(set(source_missing)), 'limitations': ['This envelope does not establish current market tradability', 'Snapshot and catalyst descriptions are source claims, not primary evidence', 'Quoted bid/ask is historical and not a broker execution or fill', 'Momentum requires timestamped bars; RVOL needs a comparable volume baseline', 'No trade caps, thresholds or hard-coded stock exclusions are imposed']}
    return output


# ========== trading_brain_research_tool.py ==========


"""
title: Trading Brain Research Context (STAGED)
author: OpenAI Engineering
description: Offline evidence-quality, quote economics, bar-feature and history context for the existing Trading Operations model. Accepts structured provider snapshots; does not call APIs or place orders.
version: 0.1.0
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from pydantic import BaseModel
MAX_SNAPSHOT_CHARS = 60000
MAX_DECISION_CHARS = 12000
MAX_BARS_CHARS = 100000
MEMORY_DB = Path('/app/backend/data/trading_brain_research/finmem.sqlite3')

class Tools:
    """Research-only augmentation. No broker, subprocess or network access."""

    def __init__(self):
        self.valves = self.Valves()

    class Valves(BaseModel):
        pass

    async def trading_brain_research(self, ticker: str, snapshot_json: str, as_of_utc: str, decision_json: str='{}', bars_json: str='[]', average_daily_volume: Optional[float]=None, scenario_quantity: int=100) -> str:
        """Combine actual supplied market evidence into a structured research-context packet.

        :param ticker: Exact ticker from the supplied market snapshot (e.g. MYGN).
        :param snapshot_json: JSON from the existing market-data tool, including observation_timestamp_utc and candidates or observation. NOT a news claim.
        :param as_of_utc: ISO-8601 time with timezone, used for point-in-time analysis.
        :param decision_json: Optional previous analyst decision object for advisory comparison; never changes its action.
        :param bars_json: Optional timestamped OHLCV list. No bars means null momentum values, not invented data.
        :param average_daily_volume: Optional independently supplied comparable-volume baseline. Null means unknown RVOL.
        :param scenario_quantity: Hypothetical share quantity for spread-cost maths, not an order size or cap.
        """
        try:
            if not isinstance(snapshot_json, str) or len(snapshot_json) > MAX_SNAPSHOT_CHARS:
                raise ValueError('snapshot_json exceeds research size limit')
            if not isinstance(decision_json, str) or len(decision_json) > MAX_DECISION_CHARS:
                raise ValueError('decision_json exceeds research size limit')
            if not isinstance(bars_json, str) or len(bars_json) > MAX_BARS_CHARS:
                raise ValueError('bars_json exceeds research size limit')
            raw = json.loads(snapshot_json)
            decision = json.loads(decision_json)
            bars = json.loads(bars_json)
            if not isinstance(raw, dict):
                raise ValueError('snapshot must be a JSON object')
            if not isinstance(decision, dict):
                raise ValueError('decision must be a JSON object')
            raw = normalise_snapshot(raw, ticker=ticker, as_of_utc=as_of_utc)
            bars = normalise_bars(bars, ticker=ticker)
            if not 1 <= scenario_quantity <= 100000:
                raise ValueError('scenario_quantity must be 1..100000')
            if average_daily_volume is not None and average_daily_volume <= 0:
                raise ValueError('comparative volume must be positive')
            if not decision:
                decision = None
            db = None
            if MEMORY_DB.is_file():
                import sqlite3
                db = sqlite3.connect('file:' + str(MEMORY_DB) + '?mode=ro', uri=True, timeout=4)
                db.row_factory = sqlite3.Row
            try:
                result = compile_context(raw, ticker=ticker, as_of_utc=as_of_utc, decision=decision, bars=bars, average_daily_volume=average_daily_volume, quantity=scenario_quantity, memory_db=db)
            finally:
                if db is not None:
                    db.close()
            serialized = json.dumps(result, ensure_ascii=False, separators=(',', ':'))
            if len(serialized) > 35000:
                raise ValueError('research result too large')
            return serialized
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            return json.dumps({'ok': False, 'error': 'invalid_research_input', 'error_type': type(exc).__name__, 'research_only': True, 'broker_orders': 0})

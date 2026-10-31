"""Free-tier Alpha Vantage DAILY research adapter. No broker or order endpoints.

Secrets are read only from the host's private key file, never returned. Data is
EOD/daily (not a substitute for current T212 executable quotes).
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import re
import sqlite3
import time
from urllib.parse import urlencode
from urllib.request import urlopen

DEFAULT_KEY_FILE = Path.home() / ".config/deepseek-runtime/data-api.env"
DEFAULT_DB = Path.home() / ".local/state/deepseek-runtime/alpha_vantage_cache.sqlite3"
SYMBOL = re.compile(r"[A-Z0-9][A-Z0-9._^-]{0,20}\Z")
MAX_REQUESTS_DAILY = 25
CACHE_TTL_SECONDS = 3600


def _key(path: Path) -> str | None:
    if not path.is_file():
        return None
    for line in path.read_text().splitlines():
        if line.startswith("ALPHAVANTAGE_API_KEY="):
            value = line.partition("=")[2].strip().strip('"').strip("'")
            return value if re.fullmatch(r"[A-Za-z0-9]{8,128}", value) else None
    return None


def _database(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    connection = sqlite3.connect(str(path), timeout=15, isolation_level=None)
    if path.is_file():
        os.chmod(path, 0o600)
    connection.execute("CREATE TABLE IF NOT EXISTS quota_day(day TEXT PRIMARY KEY, used INTEGER NOT NULL)")
    connection.execute("CREATE TABLE IF NOT EXISTS daily_cache(symbol TEXT PRIMARY KEY, fetched_at INTEGER NOT NULL, payload TEXT NOT NULL)")
    return connection


def daily_bars(symbol: str, *, key_file: Path = DEFAULT_KEY_FILE,
               db_file: Path = DEFAULT_DB, fetch=urlopen,
               clock=time.time) -> dict:
    if not isinstance(symbol, str):
        return {"ok": False, "error": "invalid_symbol"}
    sym = symbol.strip().upper()
    if not SYMBOL.fullmatch(sym):
        return {"ok": False, "error": "invalid_symbol"}
    api_key = _key(Path(key_file))
    if not api_key:
        return {"ok": False, "error": "alpha_vantage_key_not_configured"}
    moment = int(clock())
    utc_day = dt.datetime.fromtimestamp(moment, dt.timezone.utc).date().isoformat()
    with _database(Path(db_file)) as db:
        db.execute("BEGIN IMMEDIATE")
        cached = db.execute("SELECT fetched_at,payload FROM daily_cache WHERE symbol=?", (sym,)).fetchone()
        if cached and 0 <= moment - cached[0] < CACHE_TTL_SECONDS:
            db.execute("COMMIT")
            result = json.loads(cached[1])
            return {**result, "cached": True, "cache_age_seconds": moment - cached[0]}
        used = db.execute("SELECT used FROM quota_day WHERE day=?", (utc_day,)).fetchone()
        count = used[0] if used else 0
        if count >= MAX_REQUESTS_DAILY:
            db.execute("COMMIT")
            return {"ok": False, "error": "local_free_daily_quota_exhausted",
                    "provider": "Alpha Vantage", "day_utc": utc_day}
        db.execute("INSERT INTO quota_day(day,used) VALUES (?,1) ON CONFLICT(day) DO UPDATE SET used=used+1", (utc_day,))
        db.execute("COMMIT")
    query = urlencode({"function": "TIME_SERIES_DAILY", "symbol": sym,
                       "outputsize": "compact", "apikey": api_key})
    try:
        with fetch("https://www.alphavantage.co/query?" + query, timeout=20) as response:
            raw = response.read(450000)
        content = json.loads(raw)
    except Exception as exc:
        return {"ok": False, "error": "alpha_vantage_transport_error", "error_type": type(exc).__name__,
                "symbol": sym}
    series = content.get("Time Series (Daily)") if isinstance(content, dict) else None
    if not isinstance(series, dict) or not series:
        status = ("provider_entitlement_or_quota_notice" if isinstance(content, dict)
                  and ("Information" in content or "Note" in content)
                  else "provider_data_error")
        return {"ok": False, "error": status, "symbol": sym, "provider": "Alpha Vantage"}
    last_dates = sorted(series.keys(), reverse=True)[:3]
    bars = [{"date": date, "open": series[date].get("1. open"),
             "high": series[date].get("2. high"), "low": series[date].get("3. low"),
             "close": series[date].get("4. close"), "volume": series[date].get("5. volume")}
            for date in last_dates]
    result = {"ok": True, "provider": "Alpha Vantage",
              "feed": "TIME_SERIES_DAILY", "is_intraday": False, "symbol": sym,
              "latest_date": last_dates[0], "bars": bars,
              "fetched_at_utc": dt.datetime.fromtimestamp(moment, dt.timezone.utc).isoformat(),
              "cached": False}
    with _database(Path(db_file)) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("INSERT INTO daily_cache(symbol,fetched_at,payload) VALUES (?,?,?) "
                   "ON CONFLICT(symbol) DO UPDATE SET fetched_at=excluded.fetched_at,payload=excluded.payload",
                   (sym,moment,json.dumps(result,separators=(",",":"))))
        db.execute("COMMIT")
    return result

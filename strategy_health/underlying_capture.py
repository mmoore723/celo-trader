"""Independent, GET-only last-trade observation recorder. Never places orders.

Polling records what was received, not every exchange print. Trade timestamps
are never replaced by quote timestamps. Restart recovery reads persisted trades.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import sqlite3
import time
from zoneinfo import ZoneInfo

import requests

SOURCE = 'tradier_consolidated_v1'
BASE = 'https://api.tradier.com/v1'
CADENCE_SECONDS = 5
DDL = '''CREATE TABLE IF NOT EXISTS underlying_trade_observations (
 id INTEGER PRIMARY KEY, broker_account_id TEXT NOT NULL, paper INTEGER NOT NULL,
 ticker TEXT NOT NULL, received_at TEXT NOT NULL, trade_at TEXT,
 last REAL, last_size REAL, trade_time_ms TEXT, source TEXT NOT NULL,
 age_seconds REAL, validation TEXT NOT NULL, trade_ids_json TEXT NOT NULL,
 raw_json TEXT NOT NULL,
 UNIQUE(broker_account_id,paper,ticker,received_at)
)'''


def aware(value):
    stamp = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('Timestamp needs timezone')
    return stamp


def watched_trades(rows, now):
    """Keep open trades and closed trades through their saved native deadline."""
    watched, missing = {}, []
    for row in rows:
        try:
            context = json.loads(row['strategy_context_json'] or '{}')
            deadline = aware(context.get('exit_deadline'))
        except (ValueError, TypeError, AttributeError):
            deadline = None
        if row['status'] == 'open' or (deadline is not None and deadline + timedelta(seconds=30) >= now):
            watched.setdefault(row['ticker'], []).append(row['id'])
            if deadline is None:
                missing.append(row['id'])
        elif deadline is None:
            missing.append(row['id'])
    return watched, missing


def number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) and value >= 0 else None
    except (ValueError, TypeError):
        return None


def observation(raw, received, ids):
    last, size = number(raw.get('last')), number(raw.get('last_volume'))
    errors = []
    if not last:
        errors.append('missing_or_invalid_last')
    stamp, age = None, None
    try:
        stamp = datetime.fromtimestamp(float(raw['trade_date']) / 1000, timezone.utc)
        if stamp.year < 2000:
            raise ValueError('Invalid trade date')
        age = (received - stamp).total_seconds()
        if age < 0:
            errors.append('trade_time_after_receipt')
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        stamp = None
        errors.append('missing_or_invalid_trade_time')
    # Diagnostic only. This is not an entry/exit freshness rule.
    if age is not None and age > CADENCE_SECONDS * 2:
        errors.append('last_trade_older_than_two_polls')
    return (received.isoformat(), stamp.isoformat() if stamp else None,
            last, size, str(raw.get('trade_date')) if raw.get('trade_date') is not None else None,
            SOURCE, age, ','.join(errors) or 'recorded', json.dumps(sorted(ids)),
            json.dumps(raw, separators=(',', ':'), allow_nan=False))


@contextmanager
def connect(path):
    conn = sqlite3.connect(path, timeout=0.2)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def read_watch(path, account, paper, now):
    # Bound the read and fail explicitly rather than silently truncate evidence.
    start = time.monotonic()
    with connect(path) as conn:
        conn.set_progress_handler(lambda: int(time.monotonic() - start > .2), 1000)
        rows = conn.execute('''SELECT id,ticker,status,strategy_context_json FROM trades
            WHERE broker_account_id=? AND paper=?
            AND (status='open' OR substr(entry_time,1,10)=?) LIMIT 2001''',
            (account, int(paper), now.astimezone(ZoneInfo('America/New_York')).date().isoformat())).fetchall()
    if len(rows) > 2000:
        raise ValueError('watch_inventory_exceeds_capture_limit')
    return watched_trades(rows, now)


def save(path, account, paper, watched, quotes, received):
    count, problems = 0, {}
    by_symbol = {q.get('symbol'): q for q in quotes}
    with connect(path) as conn:
        conn.execute(DDL)
        conn.execute('''CREATE INDEX IF NOT EXISTS idx_underlying_trade_capture
            ON underlying_trade_observations(broker_account_id,paper,ticker,received_at)''')
        for symbol, ids in watched.items():
            raw = by_symbol.get(symbol, {'symbol': symbol})
            values = observation(raw, received, ids)
            if values[7] != 'recorded':
                problems[symbol] = values[7]
            cur = conn.execute('''INSERT OR IGNORE INTO underlying_trade_observations
                (broker_account_id,paper,ticker,received_at,trade_at,last,last_size,
                 trade_time_ms,source,age_seconds,validation,trade_ids_json,raw_json)
                 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''', (account, int(paper), symbol, *values))
            count += cur.rowcount
    return count, problems


class Feed:
    """Only two whitelisted read endpoints; no execution client or order methods."""
    def __init__(self, key):
        if not key:
            raise ValueError('missing_production_tradier_token')
        self.headers = {'Authorization': f'Bearer {key}', 'Accept': 'application/json'}
        self.clock_cache = None
        self.clock_cached_at = 0

    def get(self, endpoint, params=None):
        if endpoint not in {'/markets/clock', '/markets/quotes'}:
            raise ValueError('capture_endpoint_not_allowed')
        if endpoint == '/markets/clock' and self.clock_cache is not None and time.monotonic() - self.clock_cached_at < 30:
            return self.clock_cache
        response = requests.get(BASE + endpoint, headers=self.headers,
                                params=params, timeout=(2, 5), allow_redirects=False)
        received = datetime.now(timezone.utc)
        response.raise_for_status()
        result = response.json(), received
        if endpoint == '/markets/clock':
            self.clock_cache, self.clock_cached_at = result, time.monotonic()
        return result


def collect(path, account, paper, feed, now):
    watched, missing = read_watch(path, account, paper, now)
    health = {'watching': len(watched), 'missing_deadline_trade_ids': missing,
              'rows_saved': 0, 'quote_problems': {}}
    clock, _ = feed.get('/markets/clock')
    state = (clock.get('clock') or {}).get('state')
    if state not in {'open', 'closed', 'premarket', 'postmarket'}:
        raise ValueError('unavailable_market_clock')
    health['market_state'] = state
    # Keep polling through postmarket for outstanding horizons, including the
    # session-close observation. Closed-session quotes stay visibly stale.
    if not watched or state in {'closed', 'premarket'}:
        health['status'] = 'waiting_for_positions' if not watched else 'waiting_for_market'
        return health
    if len(watched) > 50:
        raise ValueError('capture_symbol_limit_exceeded')
    payload, received = feed.get('/markets/quotes', {'symbols': ','.join(sorted(watched)), 'greeks': 'false'})
    quotes = (payload.get('quotes') or {}).get('quote') or []
    if isinstance(quotes, dict):
        quotes = [quotes]
    count, problems = save(path, account, paper, watched, quotes, received)
    health.update(rows_saved=count, quote_problems=problems,
                  last_collection_at=received.isoformat(),
                  status='degraded' if problems else 'collecting')
    return health


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--user', required=True)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    from auth.context import set_current_user
    from config import get_settings, get_api_keys, get_db_path, get_user_data_dir, atomic_write_json
    from config.research_snapshot import research_settings_snapshot
    set_current_user(args.user, args.user, True)
    health_path = Path(get_user_data_dir(args.user)) / 'underlying_capture_health.json'
    failures, last_success = 0, None
    feed, feed_key = None, None
    scope = None
    try:
        previous = json.loads(health_path.read_text())
        last_success = previous.get('last_successful_collection_at')
        scope = previous.get('scope')
    except (OSError, ValueError):
        pass
    while True:
        started = time.monotonic()
        now = datetime.now(timezone.utc)
        delay = CADENCE_SECONDS
        try:
            settings = get_settings()
            account = settings.get('active_broker_account_id')
            if not account:
                raise ValueError('missing_active_account')
            with research_settings_snapshot(args.user, settings):
                path = Path(get_db_path())
                if not path.is_file():
                    raise ValueError('missing_trade_database')
                from hashlib import sha256
                current_scope = sha256((str(path) + ':' + account).encode()).hexdigest()[:16]
                if current_scope != scope:
                    last_success, scope = None, current_scope
                key = get_api_keys().get('tradier_market_api_key')
                if feed is None or key != feed_key:
                    feed, feed_key = Feed(key), key
                # Scope comes from frozen settings; no writes to settings.
                result = collect(path, account, bool(settings.get('paper_trading', True)),
                                 feed, now)
            failures = 0
            if result.get('status') == 'collecting':
                last_success = result['last_collection_at']
            if result.get('market_state') in {'closed', 'premarket'}:
                delay = 30
        except Exception as exc:
            failures += 1
            delay = min(60, 5 * 2 ** min(failures, 4))
            response = getattr(exc, 'response', None)
            status = getattr(response, 'status_code', None)
            if status == 429:
                try:
                    delay = max(delay, min(300, float(response.headers.get('Retry-After', 60))))
                except (ValueError, TypeError):
                    delay = 60
            # Do not log response bodies, URLs, tokens or account details.
            result = {'status': 'blocked', 'error': type(exc).__name__, 'http_status': status,
                      'reason': str(exc) if isinstance(exc, ValueError) else 'capture_request_or_storage_failed'}
        result.update(heartbeat_at=datetime.now(timezone.utc).isoformat(),
                      last_successful_collection_at=last_success,
                      elapsed_seconds=round(time.monotonic() - started, 3),
                      poll_seconds=delay, failures=failures, source=SOURCE,
                      scope=scope,
                      observation_kind='forward_polled_underlying_last_trade')
        atomic_write_json(health_path, result)
        print(json.dumps(result), flush=True)
        if args.once:
            return
        time.sleep(max(.1, delay - (time.monotonic() - started)))


if __name__ == '__main__':
    main()

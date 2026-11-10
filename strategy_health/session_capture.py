"""Order-free, universe-wide session archive. Never imports an execution client.

Snapshots are not an exchange tick tape. Every listed expiration is queued,
without price, spread, strike or DTE filters. Slow rotations remain visible.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import time
import zlib
from zoneinfo import ZoneInfo

import requests

ET = ZoneInfo('America/New_York')
SOURCE = 'tradier_consolidated_v1'
ENDPOINTS = {'calendar', 'quotes', 'timesales', 'options/expirations', 'options/chains'}


def utcnow():
    return datetime.now(timezone.utc)


def objects(value):
    if value is None:
        return []
    if isinstance(value, dict):
        return [value]
    if not isinstance(value, list):
        raise ValueError('invalid_provider_list')
    return value


class Feed:
    """Market-data allowlist, quote-only POST, quota reserve, no fallback feed."""
    def __init__(self, token):
        if not token:
            raise ValueError('missing_production_tradier_token')
        self.session = requests.Session()
        self.session.headers.update(Authorization='Bearer ' + token, Accept='application/json')
        self.next_request = 0.0

    def quotes(self, symbols):
        if (not isinstance(symbols, list) or not 1 <= len(symbols) <= 600
                or any(not isinstance(s,str) or not s or ',' in s for s in symbols)):
            raise ValueError('capture_invalid_quote_batch')
        return self.get('quotes', {'symbols':','.join(symbols),'greeks':'true','includeLotSize':'true'}, quote_body=True)

    def get(self, endpoint, params=None, *, quote_body=False):
        if endpoint not in ENDPOINTS:
            raise ValueError('capture_endpoint_not_allowed')
        if quote_body and endpoint != 'quotes':
            raise ValueError('capture_post_only_quotes_allowed')
        if time.monotonic() < self.next_request:
            raise ValueError('capture_rate_budget_wait')
        # At most 30 requests/minute. Existing trading clients retain priority.
        self.next_request = time.monotonic() + 2
        if quote_body:
            response = self.session.post('https://api.tradier.com/v1/markets/quotes',
                                         data=params, timeout=(2, 8), allow_redirects=False)
        else:
            response = self.session.get('https://api.tradier.com/v1/markets/' + endpoint,
                                        params=params, timeout=(2, 8), allow_redirects=False)
        received = utcnow()
        available = response.headers.get('X-Ratelimit-Available')
        if available is not None and int(available) < 40:
            self.next_request = time.monotonic() + 60
        if response.status_code in (400, 429):
            # Quota errors can be HTTP 400; preserve the failed request, not its
            # credential-bearing exception text. Invalid requests also back off.
            self.next_request = time.monotonic() + 60
        if not 200 <= response.status_code < 300:
            raise ValueError('provider_http_' + str(response.status_code))
        return response.json(), received


def session_window(calendar, day):
    rows = objects((calendar.get('calendar') or {}).get('days', {}).get('day'))
    row = next((r for r in rows if r.get('date') == day), None)
    if row is None:
        raise ValueError('calendar_date_missing')
    if row.get('status') == 'closed':
        return None
    if row.get('status') != 'open':
        raise ValueError('calendar_status_unknown')
    # Actual production calendar exposes broker order hours (07:00-19:55),
    # not the full stock data target. Never truncate capture to those hours.
    # Target remains explicit even on shortened sessions; absent provider bars
    # are reported unresolved, never labelled a feed failure without evidence.
    return tuple(datetime.fromisoformat(day + 'T' + t).replace(tzinfo=ET) for t in ('04:00','20:00'))


def bar_stamp(row):
    value = row.get('time')
    stamp = datetime.fromisoformat(str(value))
    # Tradier timesales wall-clock fields are Eastern. Epoch is checked when
    # supplied; a disagreement is rejected, not silently shifted.
    stamp = stamp.replace(tzinfo=ET) if stamp.tzinfo is None else stamp.astimezone(ET)
    if row.get('timestamp') is not None and abs(stamp.timestamp() - float(row['timestamp'])) > 1:
        raise ValueError('bar_timestamp_disagreement')
    return stamp


class Archive:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root / 'session_capture.sqlite3', timeout=.2)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
          PRAGMA journal_mode=WAL;
          CREATE TABLE IF NOT EXISTS responses (
            id TEXT PRIMARY KEY, day TEXT, kind TEXT, ticker TEXT,
            requested_at TEXT, received_at TEXT, params TEXT, source TEXT,
            provenance TEXT, payload BLOB);
          CREATE TABLE IF NOT EXISTS tasks (
            day TEXT, kind TEXT, ticker TEXT, expiration TEXT DEFAULT '',
            next_at REAL DEFAULT 0, last_ok TEXT, failures INTEGER DEFAULT 0,
            error TEXT, PRIMARY KEY(day,kind,ticker,expiration));
          CREATE TABLE IF NOT EXISTS bars (
            day TEXT, ticker TEXT, minute TEXT, first_received_at TEXT,
            response_id TEXT, PRIMARY KEY(day,ticker,minute));
          CREATE TABLE IF NOT EXISTS contracts (
            day TEXT,ticker TEXT,symbol TEXT,expiration TEXT,first_seen TEXT,
            last_seen TEXT, last_quote TEXT, validation TEXT,
            PRIMARY KEY(day,ticker,symbol));
          CREATE TABLE IF NOT EXISTS quote_minutes (
            day TEXT,ticker TEXT,minute TEXT,received_at TEXT,fresh INTEGER,
            PRIMARY KEY(day,ticker,minute));
          CREATE INDEX IF NOT EXISTS responses_day ON responses(day,kind,ticker);
          CREATE TABLE IF NOT EXISTS chain_refreshes (
            response_id TEXT PRIMARY KEY, day TEXT, ticker TEXT, expiration TEXT,
            requested_epoch REAL, received_epoch REAL, contracts INTEGER, fresh INTEGER);
          CREATE INDEX IF NOT EXISTS chain_refreshes_scope
            ON chain_refreshes(day,ticker,expiration,received_epoch);
          CREATE TABLE IF NOT EXISTS rotation_cursor (
            day TEXT, lane TEXT, ticker TEXT,
            PRIMARY KEY(day,lane));
        ''')

    def enqueue(self, day, tickers):
        with self.db:
            for ticker in tickers:
                for kind in ('bars', 'expirations'):
                    self.db.execute('INSERT OR IGNORE INTO tasks(day,kind,ticker) VALUES (?,?,?)',
                                    (day, kind, ticker))

    def record(self, day, kind, ticker, params, requested, received, payload):
        if shutil.disk_usage(self.root).free < 1024**3:
            raise ValueError('capture_disk_reserve_below_1GB')
        raw = json.dumps(payload, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        identity = hashlib.sha256((kind+ticker+received.isoformat()).encode()+raw).hexdigest()
        self.db.execute('INSERT OR IGNORE INTO responses VALUES (?,?,?,?,?,?,?,?,?,?)',
                        (identity, day, kind, ticker, requested.isoformat(), received.isoformat(),
                         json.dumps(params), SOURCE,
                         'provider_history_received_later' if kind == 'bars' else 'forward_snapshot',
                         zlib.compress(raw)))
        return identity

    def accept(self, task, params, requested, received, payload, window):
        day, kind, ticker, expiration = (task[k] for k in ('day','kind','ticker','expiration'))
        # Preserve even rejected provider responses. Validation never erases raw
        # evidence or changes the availability timestamp of a repaired record.
        with self.db:
            identity = self.record(day, kind, ticker, params, requested, received, payload)
        with self.db:
            if kind == 'expirations':
                listing = payload.get('expirations')
                if not isinstance(listing, dict) or 'date' not in listing:
                    raise ValueError('expiration_inventory_unavailable')
                dates = listing['date']
                dates = [dates] if isinstance(dates, str) else dates
                if not isinstance(dates, list) or not dates:
                    raise ValueError('no_listed_expirations_reported')
                for expiry in dates:
                    datetime.strptime(expiry, '%Y-%m-%d')
                    self.db.execute('INSERT OR IGNORE INTO tasks(day,kind,ticker,expiration) VALUES (?,?,?,?)',
                                    (day,'chain',ticker,expiry))
            elif kind == 'chain':
                rows = objects((payload.get('options') or {}).get('option'))
                if not rows:
                    raise ValueError('empty_option_chain')
                for row in rows:
                    if not row.get('symbol'):
                        raise ValueError('contract_identity_missing')
                    validation = quote_validation(row, received)
                    self.db.execute('''INSERT INTO contracts VALUES (?,?,?,?,?,?,?,?)
                        ON CONFLICT(day,ticker,symbol) DO UPDATE SET last_seen=excluded.last_seen,
                        last_quote=CASE WHEN excluded.validation='fresh' THEN excluded.last_quote
                        ELSE contracts.last_quote END, validation=excluded.validation''',
                        (day,ticker,row['symbol'],expiration,received.isoformat(),received.isoformat(),
                         received.isoformat() if validation == 'fresh' else None,validation))
                self.db.execute('INSERT OR IGNORE INTO chain_refreshes VALUES (?,?,?,?,?,?,?,?)',
                    (identity,day,ticker,expiration,requested.timestamp(),received.timestamp(),
                     len(rows),sum(quote_validation(r,received)=='fresh' for r in rows)))
            elif kind == 'bars':
                rows = objects((payload.get('series') or {}).get('data'))
                if not rows:
                    raise ValueError('no_candles_returned')
                for row in rows:
                    stamp = bar_stamp(row)
                    if window[0] <= stamp < window[1] and stamp + timedelta(minutes=1) <= requested:
                        values = [float(row[k]) for k in ('open','high','low','close','volume')]
                        import math
                        if not all(math.isfinite(v) for v in values) or min(values[:4]) <= 0 or values[4] < 0:
                            raise ValueError('invalid_bar_values')
                        self.db.execute('INSERT OR IGNORE INTO bars VALUES (?,?,?,?,?)',
                                        (day,ticker,stamp.isoformat(),received.isoformat(),identity))
            interval = {'bars': 180, 'expirations': 3600, 'chain': 60}[kind]
            next_at = received.timestamp()+interval
            if kind == 'bars' and requested >= window[1]:
                count = self.db.execute('SELECT count(*) FROM bars WHERE day=? AND ticker=?', (day,ticker)).fetchone()[0]
                if count == int((window[1]-window[0]).total_seconds()//60):
                    next_at = 253402300799  # Completed session, no more repair requests.
            self.db.execute('''UPDATE tasks SET next_at=?,last_ok=?,failures=0,error=NULL
                WHERE day=? AND kind=? AND ticker=? AND expiration=?''',
                (next_at,received.isoformat(),day,kind,ticker,expiration))

    def fail(self, task, error, now):
        with self.db:
            self.db.execute('''UPDATE tasks SET failures=failures+1,error=?,next_at=?
                WHERE day=? AND kind=? AND ticker=? AND expiration=?''',
                (error, now.timestamp()+min(300, 10*2**min(task['failures'],5)),
                 task['day'],task['kind'],task['ticker'],task['expiration']))


def quote_validation(row, received):
    try:
        bid, ask = float(row['bid']), float(row['ask'])
        if not (0 < bid <= ask < float('inf')):
            return 'missing_or_crossed_quote'
        ages = [(received.timestamp()*1000 - float(row[k]))/1000 for k in ('bid_date','ask_date')]
        if any(not 0 <= age <= 10 for age in ages):
            return 'stale_or_future_quote'
        return 'fresh'
    except (KeyError, ValueError, TypeError):
        return 'missing_quote_or_source_time'


def chain_cadence(archive, day, ticker, now):
    """Receipt cadence, not source freshness or tick coverage. New records only."""
    rows=archive.db.execute('''WITH ordered AS (
        SELECT *,received_epoch-LAG(received_epoch) OVER (
            PARTITION BY expiration ORDER BY received_epoch,response_id) AS gap
        FROM chain_refreshes WHERE day=? AND ticker=?)
        SELECT expiration,COUNT(*) AS samples,MAX(gap) AS max_gap,
            MAX(received_epoch-requested_epoch) AS max_request_seconds,
            MIN(received_epoch) AS first_received,MAX(received_epoch) AS last_received
        FROM ordered GROUP BY expiration ORDER BY expiration''',(day,ticker)).fetchall()
    return [dict(expiration=r['expiration'],samples=r['samples'],
                 max_gap_seconds=r['max_gap'],max_request_seconds=r['max_request_seconds'],
                 first_received_at=datetime.fromtimestamp(r['first_received'],timezone.utc).isoformat(),
                 last_received_at=datetime.fromtimestamp(r['last_received'],timezone.utc).isoformat(),
                 age_seconds=max(0,now.timestamp()-r['last_received'])) for r in rows]


def summary(archive, day, tickers, window, now):
    expected = max(0, int((min(now,window[1])-window[0]).total_seconds()//60)) if window else 0
    rows = []
    for ticker in tickers:
        bars = archive.db.execute('SELECT minute FROM bars WHERE day=? AND ticker=? ORDER BY minute', (day,ticker)).fetchall()
        seen = {r[0] for r in bars}
        missing = [(window[0]+timedelta(minutes=n)).isoformat() for n in range(expected)
                   if (window[0]+timedelta(minutes=n)).isoformat() not in seen] if window else []
        tasks = [dict(r) for r in archive.db.execute('SELECT * FROM tasks WHERE day=? AND ticker=?', (day,ticker))]
        chains = [r for r in tasks if r['kind']=='chain']
        contracts = archive.db.execute('''SELECT count(*),sum(last_quote IS NOT NULL),max(last_seen)
            FROM contracts WHERE day=? AND ticker=?''',(day,ticker)).fetchone()
        quotes = archive.db.execute('''SELECT count(*),sum(fresh),max(received_at) FROM quote_minutes
            WHERE day=? AND ticker=?''',(day,ticker)).fetchone()
        cadence=chain_cadence(archive,day,ticker,now)
        rows.append(dict(ticker=ticker, expected_minutes=expected, captured_minutes=expected-len(missing),
            coverage_pct=round(100*(expected-len(missing))/expected,1) if expected else None,
            missing_minutes=missing, first_bar=bars[0][0] if bars else None,last_bar=bars[-1][0] if bars else None,
            quote_minutes=quotes[0],fresh_quote_minutes=quotes[1] or 0,last_quote_at=quotes[2],
            listed_expirations=len(chains),captured_expirations=sum(bool(r['last_ok']) for r in chains),
            contracts_discovered=contracts[0],contracts_with_fresh_snapshot=contracts[1] or 0,
            last_chain_at=contracts[2],pending_expirations=[r['expiration'] for r in chains if not r['last_ok']],
            oldest_chain_at=min((r['last_ok'] for r in chains if r['last_ok']),default=None),
            option_refresh_cadence=cadence,
            max_option_refresh_gap_seconds=max((r['max_gap_seconds'] for r in cadence if r['max_gap_seconds'] is not None),default=None),
            oldest_option_refresh_age_seconds=max((r['age_seconds'] for r in cadence),default=None),
            errors=[dict(kind=r['kind'],expiration=r['expiration'],reason=r['error']) for r in tasks if r['error']] ))
    return dict(day=day,source=SOURCE,heartbeat_at=now.isoformat(),tickers=rows,
                session_start=window[0].isoformat() if window else None,
                session_end=window[1].isoformat() if window else None,
                status='collecting' if window and window[0]<=now<=window[1] else 'outside_session',
                capture_type='polled_snapshots_and_received_history_not_tick_complete',
                contract_exclusions=[],
                limitations=['No exchange tick-completeness claim. Quotes between snapshots are not captured.',
                'Target is 04:00-20:00 Eastern on provider-confirmed market days, including shortened days. Provider availability may be shorter.',
                'All listed expirations rotate under a shared request budget; pending and stale contracts are not complete.',
                'Refresh gaps measure successful chain response receipts, not every contract price update. Unmeasured gaps are unknown, not zero.',
                'Missing bar minutes are unresolved, not fabricated zero-volume candles.',
                'Historical candles retain their later receipt time, not original decision availability.',
                'Greeks, sizes and open interest are retained exactly when supplied, with provider timestamps.'])


def select_capture_task(due_tasks, tickers, preferred_kinds, cursors=None):
    """Keep alternating priority, but never idle while eligible work is due.

    Caller supplies the existing day/next_at-filtered, ordered queue. This
    Select one ticker after the last attempted ticker in this lane, then its
    oldest due task. Separate lanes preserve candle/option alternation. Feed
    still owns pacing and quota backoff. Failed requests also yield their turn.
    """
    eligible = [row for row in due_tasks
                if row['ticker'] in tickers and row['kind'] in ('bars', 'expirations', 'chain')]
    preferred = [row for row in eligible if row['kind'] in preferred_kinds]
    pool = preferred or eligible
    if not pool:
        return None
    lane = 'bars' if pool[0]['kind'] == 'bars' else 'options'
    pool = [row for row in pool if ('bars' if row['kind'] == 'bars' else 'options') == lane]
    order = list(dict.fromkeys(tickers))
    previous = (cursors or {}).get(lane)
    if previous in order:
        offset = order.index(previous) + 1
        order = order[offset:] + order[:offset]
    by_ticker = {}
    for row in pool:
        by_ticker.setdefault(row['ticker'], row)
    return next(by_ticker[ticker] for ticker in order if ticker in by_ticker)


def reserve_capture_task(archive, day, due_tasks, tickers, preferred_kinds):
    """Persist the attempt cursor before network I/O so restarts stay fair."""
    cursors = dict(archive.db.execute(
        'SELECT lane,ticker FROM rotation_cursor WHERE day=?', (day,)).fetchall())
    task = select_capture_task(due_tasks, tickers, preferred_kinds, cursors)
    if task is not None:
        lane = 'bars' if task['kind'] == 'bars' else 'options'
        with archive.db:
            archive.db.execute('INSERT OR REPLACE INTO rotation_cursor VALUES (?,?,?)',
                               (day, lane, task['ticker']))
    return task


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--user', required=True)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    from auth.context import set_current_user
    from config import get_settings, get_api_keys, get_user_data_dir, atomic_write_json
    from config.research_universe import selected_tickers
    set_current_user(args.user,args.user,True)
    root = Path(get_user_data_dir(args.user))
    archive = Archive(root / 'session_capture')
    feed = Feed(get_api_keys().get('tradier_market_api_key'))
    calendar, calendar_month = None, None
    last_quotes, last_summary, last_recovery, rotation = 0., 0., 0., 0
    previous = {}
    enrolled = None
    health_path = root/'session_capture_health.json'
    try:
        previous = json.loads(health_path.read_text())
    except (OSError, ValueError):
        pass
    while True:
        now = utcnow()
        local = now.astimezone(ET)
        day = local.date().isoformat()
        try:
            tickers = selected_tickers(get_settings())
            if tickers is None:
                raise ValueError('approved_universe_not_explicitly_configured')
            selection = (day,tuple(tickers))
            if selection != enrolled:
                archive.enqueue(day,tickers)
                enrolled = selection
            if calendar_month != day[:7]:
                calendar, received = feed.get('calendar',dict(month=local.month,year=local.year))
                with archive.db:
                    archive.record(day,'calendar','',{},now,received,calendar)
                calendar_month = day[:7]
            window = session_window(calendar,day)
            # Candle recovery continues for an hour after the last session minute.
            active = window and window[0]<=now<=window[1]+timedelta(hours=1)
            # Restart after a session: repair only sessions previously enrolled.
            # Recovered candles keep their later receipt time. Never backfill
            # quotes using a current quote or invent an unseen option snapshot.
            if time.monotonic() >= feed.next_request and time.monotonic()-last_recovery>=60:
                oldest=(local.date()-timedelta(days=9)).isoformat()
                pending=archive.db.execute('''SELECT * FROM tasks WHERE kind='bars' AND day<?
                    AND day>=? AND next_at<=? ORDER BY next_at,day,ticker''',(day,oldest,now.timestamp())).fetchall()
                task=next((r for r in pending if r['ticker'] in tickers),None)
                if task:
                    try:
                        past_calendar=calendar
                        if task['day'][:7]!=calendar_month:
                            past_calendar,_=feed.get('calendar',dict(month=int(task['day'][5:7]),year=int(task['day'][:4])))
                            # Defer bars to the next bounded request slot.
                            time.sleep(2)
                        past_window=session_window(past_calendar,task['day'])
                        if not past_window:
                            raise ValueError('enrolled_session_calendar_closed')
                        params=dict(symbol=task['ticker'],interval='1min',session_filter='all',
                            start=past_window[0].strftime('%Y-%m-%d %H:%M'),end=past_window[1].strftime('%Y-%m-%d %H:%M'))
                        payload,received=feed.get('timesales',params)
                        archive.accept(task,params,now,received,payload,past_window)
                        atomic_write_json(archive.root/('coverage-'+task['day']+'.json'),
                                          summary(archive,task['day'],tickers,past_window,received))
                    except Exception as exc:
                        archive.fail(task,str(exc) if isinstance(exc,ValueError) else type(exc).__name__,now)
                    last_recovery=time.monotonic()
            if active and tickers and time.monotonic() >= feed.next_request:
                if now <= window[1] and time.monotonic()-last_quotes >= 5:
                    payload, received = feed.get('quotes',dict(symbols=','.join(tickers),greeks='false',includeLotSize='true'))
                    quotes = {r.get('symbol'):r for r in objects((payload.get('quotes') or {}).get('quote'))}
                    with archive.db:
                        archive.record(day,'stock_quotes','*',dict(symbols=tickers),now,received,payload)
                        for ticker in tickers:
                            fresh = int(quote_validation(quotes.get(ticker,{}),received)=='fresh')
                            archive.db.execute('''INSERT INTO quote_minutes VALUES (?,?,?,?,?)
                                ON CONFLICT(day,ticker,minute) DO UPDATE SET received_at=excluded.received_at,
                                fresh=max(quote_minutes.fresh,excluded.fresh)''',
                                (day,ticker,received.astimezone(ET).replace(second=0,microsecond=0).isoformat(),received.isoformat(),fresh))
                    last_quotes = time.monotonic()
                else:
                    # Alternate candle work and option work, preventing either
                    # the large chain inventory or bar recovery from starvation.
                    rotation += 1
                    kinds = ('bars',) if rotation%2 else ('expirations','chain')
                    tasks = archive.db.execute("SELECT * FROM tasks WHERE day=? AND next_at<=? ORDER BY CASE WHEN kind='expirations' THEN 0 ELSE 1 END,next_at,ticker,expiration",
                                               (day,now.timestamp())).fetchall()
                    task = reserve_capture_task(archive, day, tasks, tickers, kinds)
                    if task:
                        kind,ticker = task['kind'],task['ticker']
                        if kind=='bars':
                            endpoint='timesales'
                            params=dict(symbol=ticker,interval='1min',session_filter='all',
                                start=window[0].strftime('%Y-%m-%d %H:%M'),
                                end=min(now,window[1]).astimezone(ET).strftime('%Y-%m-%d %H:%M'))
                        elif kind=='expirations':
                            endpoint='options/expirations'
                            params=dict(symbol=ticker,includeAllRoots='true',strikes='false')
                        else:
                            endpoint='options/chains'
                            params=dict(symbol=ticker,expiration=task['expiration'],greeks='true')
                        try:
                            payload,received=feed.get(endpoint,params)
                            archive.accept(task,params,now,received,payload,window)
                        except Exception as exc:
                            archive.fail(task,str(exc) if isinstance(exc,ValueError) else type(exc).__name__,now)
            if time.monotonic()-last_summary>=15 or args.once:
                previous=summary(archive,day,tickers,window,utcnow())
                atomic_write_json(health_path,previous)
                atomic_write_json(archive.root/('coverage-'+day+'.json'),previous)
                last_summary=time.monotonic()
        except Exception as exc:
            previous={**previous,'status':'blocked','heartbeat_at':utcnow().isoformat(),
                      'error':str(exc) if isinstance(exc,ValueError) else type(exc).__name__}
            atomic_write_json(health_path,previous)
        if args.once:
            return
        time.sleep(1)


if __name__ == '__main__':
    main()

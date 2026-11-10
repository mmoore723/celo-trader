"""Durable research quote registrations. Market-data-only holding observer.

Registrations are capture requests, never experiment enrollment or order intents.
Source databases are read-only. Old holding archives are not changed.
"""
import argparse
from contextlib import closing
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
import time

from strategy_health.session_capture import Feed, ET, objects, quote_validation

CADENCE = 5
BATCH = 600
OCC = re.compile(r'^[A-Z.]{1,6}[0-9]{6}[CP][0-9]{8}$')


def stamp(value):
    result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('capture_timestamp_requires_timezone')
    return result.astimezone(timezone.utc)


def source_stamp(value):
    result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    # Legacy trade/research source fields use documented Eastern wall clock.
    return (result.replace(tzinfo=ET) if result.tzinfo is None else result).astimezone(timezone.utc)


def scope_key(account, mode):
    return hashlib.sha256(json.dumps([account, mode]).encode()).hexdigest()


def sessions(payload):
    result = []
    for row in objects((payload.get('calendar') or {}).get('days', {}).get('day')):
        if row.get('status') == 'open':
            result.append(tuple(datetime.fromisoformat(row['date']+'T'+row['open'][k]).replace(tzinfo=ET)
                                for k in ('start', 'end')))
    return sorted(result)


def capture_horizon(entry, calendar, metadata):
    """Conservative capture envelope, not a trade exit or invented policy."""
    same = [i for i, (start, _) in enumerate(calendar) if start.date() == entry.astimezone(ET).date()]
    if not same or same[0]+1 >= len(calendar):
        raise ValueError('capture_calendar_missing_next_session')
    until = calendar[same[0]+1][1] + timedelta(seconds=60)
    for field in ('exit_deadline', 'capture_until', 'baseline_exit_deadline', 'candidate_exit_deadline'):
        if metadata.get(field):
            until = max(until, stamp(metadata[field])+timedelta(seconds=60))
    return until.astimezone(timezone.utc)


class Registry:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root/'fast_capture.sqlite3', timeout=.2)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''PRAGMA journal_mode=WAL;
          CREATE TABLE IF NOT EXISTS registrations (
            id TEXT PRIMARY KEY, account TEXT, mode TEXT, strategy TEXT, ticker TEXT,
            version TEXT, symbol TEXT, entry_at TEXT, until_at TEXT, registered_at TEXT,
            origin TEXT, origin_id TEXT, policy TEXT, metadata TEXT, readiness TEXT);
          CREATE INDEX IF NOT EXISTS capture_until ON registrations(until_at);
          CREATE TABLE IF NOT EXISTS observations (
            symbol TEXT, received_at TEXT, requested_at TEXT, validation TEXT, payload TEXT,
            PRIMARY KEY(symbol,received_at));
          CREATE TABLE IF NOT EXISTS links (
            registration TEXT, symbol TEXT, received_at TEXT,
            PRIMARY KEY(registration,symbol,received_at));
          CREATE TABLE IF NOT EXISTS polling (
            symbol TEXT PRIMARY KEY, attempted_at TEXT, received_at TEXT,
            next_at REAL DEFAULT 0, failures INTEGER DEFAULT 0, error TEXT,
            max_gap REAL DEFAULT 0, gaps_over_10 INTEGER DEFAULT 0);
          CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY, recorded_at TEXT, kind TEXT, detail TEXT);
          CREATE INDEX IF NOT EXISTS registration_contract_window ON registrations(symbol,entry_at,until_at);
          CREATE INDEX IF NOT EXISTS link_registration_receipt ON links(registration,received_at);
        ''')

    def register(self, *, account, mode, strategy, ticker, version, symbol, entry_at,
                 until_at, origin, origin_id, policy, metadata, now):
        if not account or mode not in ('paper', 'live') or not strategy or not ticker:
            raise ValueError('capture_scope_missing')
        if not OCC.fullmatch(symbol):
            raise ValueError('capture_contract_invalid')
        entry, until = stamp(entry_at), stamp(until_at)
        if entry > now or until <= entry:
            raise ValueError('capture_horizon_invalid')
        identity = hashlib.sha256(json.dumps([account,mode,strategy,ticker,version,symbol,
                                             entry.isoformat(),origin,str(origin_id)]).encode()).hexdigest()
        prior = self.db.execute('SELECT until_at FROM registrations WHERE id=?',(identity,)).fetchone()
        if prior is not None and until <= stamp(prior[0]):
            return identity  # Existing metadata is immutable; no repeated write transaction.
        readiness = 'capture_only' if version and policy else 'missing_version_or_policy'
        with self.db:
            self.db.execute('''INSERT OR IGNORE INTO registrations VALUES
              (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
              (identity,account,mode,strategy,ticker,version or '',symbol,entry.isoformat(),until.isoformat(),
               now.isoformat(),origin,str(origin_id),policy or '',json.dumps(metadata,allow_nan=False),readiness))
            prior = self.db.execute('SELECT until_at FROM registrations WHERE id=?',(identity,)).fetchone()[0]
            if until > stamp(prior):
                self.db.execute('UPDATE registrations SET until_at=? WHERE id=?',(until.isoformat(),identity))
                self.db.execute('INSERT INTO events(recorded_at,kind,detail) VALUES (?,?,?)',
                                (now.isoformat(),'horizon_extended',json.dumps({'id':identity,'before':prior,'after':until.isoformat()})))
            self.db.execute('INSERT OR IGNORE INTO polling(symbol) VALUES (?)',(symbol,))
        return identity

    def due(self, now):
        return [r[0] for r in self.db.execute('''SELECT p.symbol FROM polling p
            WHERE p.next_at<=? AND substr(p.symbol,-15,6)>=? AND EXISTS (SELECT 1 FROM registrations r
              WHERE r.symbol=p.symbol AND r.until_at>=? AND r.entry_at<=?)
            ORDER BY p.next_at,p.symbol LIMIT ?''',(now.timestamp(),now.astimezone(ET).strftime('%y%m%d'),now.isoformat(),now.isoformat(),BATCH))]

    def record(self, symbols, payload, requested, received):
        if shutil.disk_usage(self.root).free < 1024**3:
            raise ValueError('capture_disk_reserve_below_1GB')
        rows = objects((payload.get('quotes') or {}).get('quote'))
        by_symbol = {}
        for row in rows:
            symbol = row.get('symbol')
            if symbol not in symbols or symbol in by_symbol:
                raise ValueError('unexpected_or_duplicate_contract')
            by_symbol[symbol] = row
        with self.db:
            for symbol in symbols:
                raw = by_symbol.get(symbol, {'symbol':symbol,'capture_error':'missing_provider_quote'})
                valid = quote_validation(raw,received)
                inserted = self.db.execute('INSERT OR IGNORE INTO observations VALUES (?,?,?,?,?)',
                    (symbol,received.isoformat(),requested.isoformat(),valid,json.dumps(raw,allow_nan=False))).rowcount
                self.db.execute('''INSERT OR IGNORE INTO links SELECT id,?,? FROM registrations
                    WHERE symbol=? AND entry_at<=? AND until_at>=?''',
                    (symbol,received.isoformat(),symbol,requested.isoformat(),requested.isoformat()))
                if inserted:
                    prior = self.db.execute('SELECT received_at FROM polling WHERE symbol=?',(symbol,)).fetchone()[0]
                    gap = max(0,(received-stamp(prior)).total_seconds()) if prior else 0
                    self.db.execute('''UPDATE polling SET attempted_at=?,received_at=?,next_at=?,failures=0,
                        error=?,max_gap=max(max_gap,?),gaps_over_10=gaps_over_10+? WHERE symbol=?''',
                        (requested.isoformat(),received.isoformat(),requested.timestamp()+CADENCE,
                         None if valid=='fresh' else valid,gap,int(gap>10),symbol))

    def fail(self, symbols, now, reason):
        with self.db:
            for symbol in symbols:
                row = self.db.execute('SELECT failures FROM polling WHERE symbol=?',(symbol,)).fetchone()
                delay = min(300,10*2**min(row[0],5))
                self.db.execute('UPDATE polling SET attempted_at=?,next_at=?,failures=failures+1,error=? WHERE symbol=?',
                                (now.isoformat(),now.timestamp()+delay,reason,symbol))
            self.db.execute('INSERT INTO events(recorded_at,kind,detail) VALUES (?,?,?)',
                            (now.isoformat(),'request_failure',json.dumps({'contracts':symbols,'reason':reason})))

    def health(self, now):
        grouped = {}
        for r in self.db.execute('''SELECT r.*,
            (SELECT max(l.received_at) FROM links l WHERE l.registration=r.id) AS received_at,
            p.error,p.max_gap,p.gaps_over_10 FROM registrations r
            JOIN polling p ON p.symbol=r.symbol WHERE r.until_at>=?''',(now.isoformat(),)):
            group = grouped.setdefault(scope_key(r['account'],r['mode']),{})
            key = json.dumps([r['strategy'],r['ticker'],r['version']])
            b = group.setdefault(key,dict(strategy=r['strategy'],ticker=r['ticker'],version=r['version'],
                registrations=0,contracts=set(),pending=set(),late=set(),missing_inputs=set(),
                last_collection=None,max_gap_seconds=0,gaps_over_10=0,errors=set()))
            b['registrations']+=1
            expired = r['symbol'][-15:-9] < now.astimezone(ET).strftime('%y%m%d')
            if expired:
                b['errors'].add('contract_expired_no_further_polling_records_preserved')
            if r['symbol'] not in b['contracts']:
                b['contracts'].add(r['symbol']); b['gaps_over_10']+=r['gaps_over_10']
            if not expired and not r['received_at']: b['pending'].add(r['symbol'])
            if not expired and (not r['received_at'] or (now-stamp(r['received_at'])).total_seconds()>10): b['late'].add(r['symbol'])
            if r['readiness']!='capture_only': b['missing_inputs'].add(r['readiness'])
            if r['error']: b['errors'].add(r['error'])
            b['max_gap_seconds']=max(b['max_gap_seconds'],r['max_gap'])
            if r['received_at']: b['last_collection']=max(b['last_collection'] or '',r['received_at'])
        result={}
        for key,groups in grouped.items():
            result[key]=[]
            for b in groups.values():
                for field in ('contracts','pending','late'): b[field]=len(b[field])
                for field in ('errors','missing_inputs'): b[field]=sorted(b[field])
                result[key].append(b)
        return result


def discover(path, account, mode, registry, calendar, now):
    """Read existing fills and research selections without registering experiments."""
    if not Path(path).is_file():
        return {'source_database':'missing','registered':0,'blocked':{'missing_source_database':1}}
    cutoff=(now.astimezone(ET).date()-timedelta(days=10)).isoformat()
    problems={}; added=0
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True,timeout=.2)) as db:
        db.row_factory=sqlite3.Row
        started=time.monotonic()
        db.set_progress_handler(lambda:int(time.monotonic()-started>1),1000)
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        sources=[]
        if 'trades' in tables:
            sources.append(('broker_trade',db.execute('''SELECT id AS origin_id,ticker,strategy_id,contract_symbol,
                entry_time AS entry_at,strategy_context_json AS metadata FROM trades
                WHERE broker_account_id=? AND paper=? AND (entry_time>=? OR status='open')
                ORDER BY id LIMIT 10001''',(account,int(mode=='paper'),cutoff)).fetchall()))
        if {'shadow_candidates','candidate_option_quote_observations'}<=tables:
            sources.append(('research_selection',db.execute('''SELECT s.candidate_id AS origin_id,s.ticker,
                s.strategy_id,q.contract_symbol,q.observed_at AS entry_at,s.metadata_json AS metadata
                FROM shadow_candidates s JOIN candidate_option_quote_observations q
                ON s.candidate_id=q.candidate_id AND q.observation_kind='entry'
                WHERE s.broker_account_id=? AND s.observed_at>=? ORDER BY s.observed_at LIMIT 10001''',
                (account,cutoff)).fetchall()))
        if {'shadow_candidates','candidate_contract_alternatives'}<=tables:
            sources.append(('research_alternative',db.execute('''SELECT s.candidate_id AS origin_id,s.ticker,
                s.strategy_id,q.contract_symbol,q.observed_at AS entry_at,s.metadata_json AS metadata
                FROM shadow_candidates s JOIN candidate_contract_alternatives q
                ON s.candidate_id=q.candidate_id AND q.observation_kind='entry'
                WHERE s.broker_account_id=? AND s.observed_at>=? ORDER BY s.observed_at LIMIT 10001''',
                (account,cutoff)).fetchall()))
        if {'shadow_candidates','research_expiration_comparisons'}<=tables:
            sources.append(('research_expiration_study',db.execute('''SELECT s.candidate_id||':'||q.profile_version AS origin_id,
                s.ticker,s.strategy_id,
                CASE WHEN json_valid(q.state_json) THEN json_extract(q.state_json,'$.contract_symbol') END AS contract_symbol,
                CASE WHEN json_valid(q.state_json) THEN json_extract(q.state_json,'$.entry_quote_at') END AS entry_at,s.metadata_json AS metadata
                FROM shadow_candidates s JOIN research_expiration_comparisons q ON s.candidate_id=q.candidate_id
                WHERE s.broker_account_id=? AND s.observed_at>=?
                ORDER BY s.observed_at LIMIT 10001''',(account,cutoff)).fetchall()))
        for origin,rows in sources:
            if len(rows)>10000:
                problems[origin+'_source_limit_exceeded']=len(rows)
                continue  # Never silently treat a truncated inventory as complete.
            for row in rows:
                try:
                    meta=json.loads(row['metadata'] or '{}')
                    if not row['contract_symbol']:
                        raise ValueError('source_contract_missing')
                    if not row['entry_at']:
                        raise ValueError('source_entry_timestamp_missing')
                    entry=source_stamp(row['entry_at'])
                    if entry>now: raise ValueError('source_entry_in_future')
                    until=capture_horizon(entry,calendar,meta)
                    if until<now: continue
                    selected=meta.get('selected_test_policy') or {}
                    policy=selected.get('policy_version') or selected.get('version') or meta.get('authored_exit_protocol') or meta.get('exit_policy_version')
                    registry.register(account=account,mode=mode,strategy=row['strategy_id'],ticker=row['ticker'],
                        version=meta.get('strategy_version'),symbol=row['contract_symbol'] or '',entry_at=entry.isoformat(),
                        until_at=until.isoformat(),origin=origin,origin_id=row['origin_id'],policy=policy,
                        metadata={'source_snapshot':meta,'availability':'first_seen_by_capture_worker_not_verified_entry_state',
                                  'capture_envelope':'next_session_close_plus_60s_or_later_saved_deadline'},now=now)
                    added+=1
                except (ValueError,TypeError,KeyError,AttributeError) as exc:
                    reason=str(exc) if isinstance(exc,ValueError) and str(exc).startswith(('capture_','source_')) else type(exc).__name__
                    problems[reason]=problems.get(reason,0)+1
    return {'source_database':'read_only','registered':added,'blocked':problems}


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--user',required=True); parser.add_argument('--once',action='store_true')
    args=parser.parse_args()
    from auth.context import set_current_user
    from config import get_settings,get_api_keys,get_user_data_dir,atomic_write_json
    set_current_user(args.user,args.user,True)
    root=Path(get_user_data_dir(args.user)); registry=Registry(root/'fast_capture')
    lock=(registry.root/'worker.lock').open('a'); fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    feed=Feed(get_api_keys().get('tradier_market_api_key'))
    calendar=[]; refresh=discover_at=publish_at=next_batch=0.; discovery={}; last_state=None
    discovery_scope=None
    timings={}
    while True:
        now=datetime.now(timezone.utc); state='waiting_for_market'; error=None
        try:
            if time.monotonic()>=refresh:
                payload,_=feed.get('calendar',{'month':now.astimezone(ET).month,'year':now.astimezone(ET).year})
                calendar=sessions(payload)
                # Cover source discovery and next-session horizons across months.
                for adjacent in (now-timedelta(days=10),now+timedelta(days=10)):
                    if (adjacent.year,adjacent.month)==(now.year,now.month):
                        continue
                    time.sleep(2)
                    payload,_=feed.get('calendar',{'month':adjacent.month,'year':adjacent.year})
                    calendar+=sessions(payload); calendar=sorted(set(calendar))
                refresh=time.monotonic()+3600
            settings=get_settings(); account=settings.get('active_broker_account_id'); mode='paper' if settings.get('paper_trading',True) else 'live'
            active=any(a<=now<=b+timedelta(seconds=60) for a,b in calendar)
            if time.monotonic()>=discover_at or discovery_scope!=scope_key(account,mode):
                if not account: raise ValueError('capture_account_missing')
                started=time.monotonic()
                discovery=discover(root/('trades_'+mode+'.db'),account,mode,registry,calendar,now)
                timings['discovery_seconds']=time.monotonic()-started
                discovery_scope=scope_key(account,mode)
                discover_at=time.monotonic()+(10 if active else 300)
            if active:
                state='collecting'
                if time.monotonic()>=max(feed.next_request,next_batch):
                    started=time.monotonic()
                    symbols=registry.due(now)
                    timings['due_query_seconds']=time.monotonic()-started
                    if symbols:
                        next_batch=time.monotonic()+CADENCE
                        requested=datetime.now(timezone.utc)
                        try:
                            started=time.monotonic()
                            payload,received=feed.quotes(symbols)
                            timings['request_seconds']=time.monotonic()-started
                            started=time.monotonic()
                            registry.record(symbols,payload,requested,received)
                            timings['persist_seconds']=time.monotonic()-started
                            timings['last_batch_at']=received.isoformat()
                            timings['last_batch_contracts']=len(symbols)
                        except Exception as exc:
                            registry.fail(symbols,requested,str(exc) if isinstance(exc,ValueError) else type(exc).__name__)
                            raise
                    else: state='waiting_for_registrations'
        except Exception as exc:
            state='blocked'; error=str(exc) if isinstance(exc,ValueError) else type(exc).__name__
        if time.monotonic()>=publish_at or args.once:
            report={'heartbeat_at':datetime.now(timezone.utc).isoformat(),'status':state,'error':error,
                'discovery':discovery,'discovery_scope':discovery_scope,'scopes':registry.health(datetime.now(timezone.utc)),
                'batch_size':BATCH,'request_interval_seconds':CADENCE,'capture_only':True,
                'processing_timings':dict(timings),
                'experiment_evaluation_started':False}
            atomic_write_json(root/'fast_capture_health.json',report)
            signature=json.dumps([state,error,discovery.get('blocked')],sort_keys=True)
            if signature!=last_state:
                print(json.dumps({'capture_health_transition':state,'error':error,'discovery_blocked':discovery.get('blocked')}),flush=True)
                last_state=signature
            publish_at=time.monotonic()+15
        if args.once:
            registry.db.close()
            lock.close()
            return
        time.sleep(1)


if __name__=='__main__': main()

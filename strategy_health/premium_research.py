"""Account-scoped background comparisons from captured quotes, not broker calls."""
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from hashlib import sha256
import json
import sqlite3
import time
import numpy as np
from contextvars import ContextVar

BACKGROUND_ANALYSIS = ContextVar('premium_background_analysis', default=False)
ANALYSIS_DEADLINE = ContextVar('premium_analysis_deadline', default=float('inf'))
ANALYSIS_KEYS = ContextVar('premium_analysis_keys', default=None)
SEEN_KEYS = ContextVar('premium_seen_keys', default=None)

from strategy_health.premium_rules import RULES, VERSION, EXECUTION_RULES, clock, replay, net, rule_specifications

CRITERIA = dict(min_trades=50, min_sessions=20, coverage=.90,
                confidence=1-.05/len(RULES), tested_exits=len(RULES), max_gap_seconds=10,
                bootstrap_draws=4000)


def initialize(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS premium_exit_trade_cache
      (fingerprint TEXT PRIMARY KEY, at REAL NOT NULL, payload TEXT NOT NULL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS premium_exit_work
      (bucket TEXT PRIMARY KEY, account TEXT, mode TEXT, last_run REAL NOT NULL DEFAULT 0)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS premium_exit_specs
      (version TEXT PRIMARY KEY, frozen_at TEXT NOT NULL, specification TEXT NOT NULL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS premium_exit_reports
      (bucket TEXT PRIMARY KEY, updated_at TEXT NOT NULL, payload TEXT NOT NULL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS premium_exit_decisions
      (id INTEGER PRIMARY KEY, at TEXT NOT NULL, account TEXT NOT NULL, action TEXT NOT NULL,
       bucket TEXT NOT NULL, rule TEXT, report_hash TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS premium_position_state
      (trade_key TEXT PRIMARY KEY, state TEXT NOT NULL)''')
    spec=json.dumps(dict(version=VERSION,rules=rule_specifications(),criteria=CRITERIA,
        stages='50 trades across 20 sessions, followed by a separate newer 50-trade/20-session holdout; stop at fixed enrollment endpoint',
        comparison_cohort='identical entries, contracts and quantities across every candidate',
        fee_per_contract_side=.65,slippage_per_share_side=.01,quote_age_seconds=10,
        next_quote_deadline_seconds=30,scope='supplement baseline; preserve safety and session exits'),sort_keys=True)
    conn.execute('INSERT OR IGNORE INTO premium_exit_specs VALUES (?,?,?)',
                 (VERSION,datetime.now(timezone.utc).isoformat(),spec))
    frozen=conn.execute('SELECT frozen_at,specification FROM premium_exit_specs WHERE version=?',(VERSION,)).fetchone()
    if frozen[1] != spec: raise ValueError('Frozen premium specification changed; new version required')
    return frozen[0]


def metrics(values):
    values=list(values); high=running=drawdown=0.0
    for v in values:
        running+=v;high=max(high,running);drawdown=max(drawdown,high-running)
    gains=sum(max(0,v) for v in values);loss=-sum(min(0,v) for v in values)
    return dict(trades=len(values),net_pnl=round(sum(values),2),worst_loss=min(values,default=None),
        win_rate=round(100*sum(v>0 for v in values)/len(values),2) if values else None,
        profit_factor=gains/loss if loss else ('infinite' if gains else None),drawdown=round(drawdown,2))


def stage_cutoff(samples, frozen):
    """Fixed enrollment endpoint: first session reaching 50 entries and 20 sessions."""
    from zoneinfo import ZoneInfo
    counts=Counter(clock(s['observed_at']).astimezone(ZoneInfo('America/New_York')).date().isoformat()
                   for s in samples if clock(s['observed_at'])>=clock(frozen))
    n=0
    for sessions,(day,count) in enumerate(sorted(counts.items()),1):
        n+=count
        if n>=CRITERIA['min_trades'] and sessions>=CRITERIA['min_sessions']:
            return day
    return None


def assess(rows, attempted, *, tested_exits=None):
    """Paired day-cluster uncertainty, adjusted for the actual candidate count."""
    tested_exits=len(RULES) if tested_exits is None else tested_exits
    if type(tested_exits) is not int or tested_exits<1:
        raise ValueError('Positive exit count required')
    confidence=1-.05/tested_exits
    ordered=sorted(rows,key=lambda r:(r['exit_at'],r['id']))
    base=metrics(r['baseline_net'] for r in ordered)
    candidate=metrics(r['candidate_net'] for r in sorted(rows,key=lambda r:(r.get('candidate_exit_at',r['exit_at']),r['id'])))
    daily=defaultdict(list)
    from zoneinfo import ZoneInfo
    for row in rows: daily[clock(row['entry_at']).astimezone(ZoneInfo('America/New_York')).date().isoformat()].append(row['candidate_net']-row['baseline_net'])
    coverage=len(rows)/attempted if attempted else 0
    bounds=None
    if len(daily)>=2:
        groups=list(daily.values()); sums=np.array([sum(g) for g in groups]); counts=np.array([len(g) for g in groups])
        rng=np.random.default_rng(1731); indexes=rng.integers(0,len(groups),(CRITERIA['bootstrap_draws'],len(groups)))
        draws=sums[indexes].sum(axis=1)/counts[indexes].sum(axis=1)
        alpha=(1-confidence)/2
        bounds=[float(v) for v in np.quantile(draws,[alpha,1-alpha])]
    gates=dict(trades=len(rows)>=50,sessions=len(daily)>=20,coverage=coverage>=.90,
        net_profit=candidate['net_pnl']>0,improvement=bool(bounds and bounds[0]>0),
        drawdown=candidate['drawdown']<=base['drawdown'],
        worst_loss=bool(rows) and candidate['worst_loss']>=base['worst_loss'])
    return dict(baseline=base,candidate=candidate,paired_trades=len(rows),sessions=len(daily),
        coverage=coverage,improvement_interval=bounds,confidence=confidence,tested_exits=tested_exits,
        mean_improvement=sum(r['candidate_net']-r['baseline_net'] for r in rows)/len(rows) if rows else None,
        baseline_winners_to_losses=sum(r['baseline_net']>0 and r['candidate_net']<0 for r in rows),
        gates=gates,evidence_passed=all(gates.values()))


class CaptureReader:
    def __init__(self, path):
        self.db=None
        if path.is_file():
            self.db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=.2)
            self.db.row_factory=sqlite3.Row
    def close(self):
        if self.db: self.db.close()
    def observations(self, sample, account, mode, version):
        if not self.db: raise ValueError('fast_capture_database_missing')
        if time.monotonic()>ANALYSIS_DEADLINE.get():
            raise TimeoutError('Background analysis time budget reached')
        started=time.monotonic()
        self.db.set_progress_handler(lambda:int(time.monotonic()-started>2),1000)
        reg=self.db.execute('''SELECT * FROM registrations WHERE account=? AND mode=?
            AND origin=? AND origin_id=? AND symbol=? AND version=?
            ORDER BY registered_at LIMIT 1''',
            (account,mode,sample.get('capture_origin','research_selection'),sample['candidate_id'],sample['entry_contract'],version)).fetchone()
        if not reg: raise ValueError('research_contract_not_registered')
        if clock(reg['registered_at'])>clock(sample['entry_quote_at'])+timedelta(seconds=10):
            raise ValueError('late_contract_registration')
        rows=self.db.execute('''SELECT o.received_at,o.payload FROM links l JOIN observations o
            ON o.symbol=l.symbol AND o.received_at=l.received_at WHERE l.registration=? ORDER BY o.received_at LIMIT 100001''',(reg['id'],)).fetchall()
        if len(rows)>100000: raise ValueError('quote_budget_exceeded')
        return [dict(received_at=r['received_at'],quote=json.loads(r['payload'])) for r in rows]


def compare(conn, reader, *, samples, completed, account, mode, strategy, ticker, version, partial=False, native_exits=None, exact_baseline=None):
    frozen=initialize(conn)
    key=json.dumps([account,mode,strategy,ticker,version,VERSION,(exact_baseline or {}).get('fingerprint','research_control')],separators=(',',':'))
    saved=conn.execute('SELECT payload FROM premium_exit_reports WHERE bucket=?',(key,)).fetchone()
    if saved and json.loads(saved[0]).get('evaluation_closed'):
        return json.loads(saved[0])
    controls={str(r['id']):r for r in completed}
    outcomes={rule:[] for rule in RULES}; exclusions={rule:Counter() for rule in RULES}
    prospective={rule:[] for rule in RULES}; attempted=0; enrolled_sessions=set(); pending=0
    cutoff=stage_cutoff(samples,frozen)
    from zoneinfo import ZoneInfo
    def day(sample): return clock(sample['observed_at']).astimezone(ZoneInfo('America/New_York')).date().isoformat()
    holdout_samples=[s for s in samples if cutoff and day(s)>cutoff]
    holdout_cutoff=stage_cutoff(holdout_samples,frozen)
    if holdout_cutoff:
        samples=[s for s in samples if day(s)<=holdout_cutoff]
    selection_attempted=sum(clock(s['observed_at'])>=clock(frozen) and (not cutoff or day(s)<=cutoff) for s in samples)
    holdout_attempted=sum(clock(s['observed_at'])>=clock(frozen) and bool(cutoff and day(s)>cutoff) for s in samples)
    for raw in samples:
        sample=dict(raw); fresh=clock(sample['observed_at'])>=clock(frozen)
        attempted+=int(fresh)
        if fresh:
            from zoneinfo import ZoneInfo
            enrolled_sessions.add(clock(sample['observed_at']).astimezone(ZoneInfo('America/New_York')).date())
        control=controls.get(str(sample['candidate_id']))
        if fresh and not control: pending+=1
        reason=sample.get('input_problem')
        if not control: reason='baseline_not_complete'
        elif not sample.get('entry_contract') or not sample.get('entry_ask'): reason='entry_contract_or_price_missing'
        path=((native_exits or {}).get(sample['candidate_id'],{}).get('premium_path') or {})
        if partial and path.get('partial_bid') is not None and not path.get('partial_at'):
            reason='partial_baseline_timestamp_missing'
        cache_key=sha256(json.dumps([key,frozen,sample,control,path,partial],sort_keys=True,default=str).encode()).hexdigest()
        cached=conn.execute('SELECT at,payload FROM premium_exit_trade_cache WHERE fingerprint=?',(cache_key,)).fetchone()
        if cached and time.time()-cached[0]<3600:
            cache=json.loads(cached[1])
            for rule,evidence in cache['trades'].items():
                outcomes[rule].append(evidence)
                if fresh: prospective[rule].append(evidence)
            if fresh:
                for rule,counts in cache['exclusions'].items(): exclusions[rule].update(counts)
            continue
        before={rule:Counter(counts) for rule,counts in exclusions.items()}
        try:
            quotes=[] if reason else reader.observations(sample,account,mode,version)
        except (ValueError,sqlite3.Error,TypeError) as exc:
            reason=str(exc)
        trade_results={}
        for rule in RULES:
            if reason:
                if fresh: exclusions[rule][reason]+=1
                continue
            quantity=sample.get('quantity',2 if partial else 1)
            result=replay(rule,quotes,entry=float(sample['entry_ask']),entry_at=control['entry_at'],
                          end=control['exit_at'],symbol=sample['entry_contract'],quantity=quantity,
                          actual_entry=sample.get('actual_entry',False),native_legs=sample.get('native_legs',()))
            if result['status']=='missing_next_quote' or result.get('max_gap_seconds',float('inf'))>10:
                if fresh: exclusions[rule]['missing_next_quote' if result['status']=='missing_next_quote' else 'quote_path_gap_over_10s']+=1
                continue
            candidate=result['net_pnl']/(2 if partial else 1) if 'net_pnl' in result else control['pnl']
            if partial and result.get('exit') and path.get('partial_bid') is not None:
                if clock(path['partial_at'])<=clock(result['exit']['received_at']):
                    candidate=(net(float(sample['entry_ask']),float(path['partial_bid']))+candidate)/2
            evidence=dict(id=sample['candidate_id'],entry_at=control['entry_at'],exit_at=control['exit_at'],
                candidate_exit_at=(result.get('exit') or {}).get('received_at',control['exit_at']),
                baseline_net=control['pnl'],candidate_net=candidate,signal=result.get('signal'),
                exit_quote=result.get('exit'),kind='hypothetical_not_fill',prospective=fresh)
            trade_results[rule]=evidence
        # Every candidate is scored on the identical entry/contract cohort.
        # A missing next bid in one variant cannot give another an easier set.
        if len(trade_results)==len(RULES):
            for rule,evidence in trade_results.items():
                outcomes[rule].append(evidence)
                if fresh: prospective[rule].append(evidence)
        elif fresh:
            for rule in trade_results: exclusions[rule]['another_variant_missing_required_quote']+=1
        cache=dict(trades=trade_results if len(trade_results)==len(RULES) else {},
                   exclusions={rule:dict(exclusions[rule]-before[rule]) for rule in RULES})
        conn.execute('INSERT OR REPLACE INTO premium_exit_trade_cache VALUES (?,?,?)',
                     (cache_key,time.time(),json.dumps(cache)))
        conn.commit()  # Durable progress if the worker's time budget interrupts this bucket.
    # Stop on enrollment counts, never on P&L. A failed first evaluation cannot
    # become a winner by silently adding trades until significance appears.
    selection_complete=bool(cutoff) and not any(clock(s['observed_at'])>=clock(frozen) and day(s)<=cutoff and str(s['candidate_id']) not in controls for s in samples)
    closed=bool(holdout_cutoff) and pending==0
    from strategy_health.premium_approval import execution_certified
    certified=execution_certified()
    candidates=[]
    for rule,label in RULES.items():
        selection_rows=[r for r in prospective[rule] if not cutoff or day({'observed_at':r['entry_at']})<=cutoff]
        holdout_rows=[r for r in prospective[rule] if cutoff and day({'observed_at':r['entry_at']})>cutoff]
        selection=assess(selection_rows,selection_attempted,tested_exits=len(outcomes))
        result=assess(holdout_rows,holdout_attempted,tested_exits=len(outcomes))
        qualified=selection_complete and selection['evidence_passed'] and closed and result['evidence_passed']
        result['evidence_passed']=qualified
        candidates.append(dict(rule=rule,label=label,version=VERSION,**result,
            selection=selection,selection_complete=selection_complete,holdout_started_after=cutoff,
            rule_specification=rule_specifications()[rule],research_only=rule not in EXECUTION_RULES,
            historical=assess([r for r in outcomes[rule] if not r['prospective']],len(samples)-attempted),
            attempted=holdout_attempted,selection_attempted=selection_attempted,exclusions=dict(exclusions[rule]),
            status='complete' if closed else 'collecting',
            recommendation='PROPOSE CHANGE' if qualified and exact_baseline else 'INSUFFICIENT EVIDENCE',
            promotion_ready=bool(exact_baseline) and rule in EXECUTION_RULES and closed and result['evidence_passed'] and certified and mode=='paper',trades=outcomes[rule]))
    report=dict(bucket=key,strategy_id=strategy,ticker=ticker,strategy_version=version,account=account,mode=mode,
        specification=VERSION,frozen_at=frozen,criteria=CRITERIA,candidates=candidates,evaluation_closed=closed,
        exact_baseline=exact_baseline,selection_cutoff=cutoff,holdout_cutoff=holdout_cutoff,
        baseline_source='broker-confirmed native exits' if exact_baseline else 'research exit simulation; not activation evidence',
        updated_at=datetime.now(timezone.utc).isoformat())
    report['fingerprint']=sha256(json.dumps({k:v for k,v in report.items() if k!='updated_at'},sort_keys=True).encode()).hexdigest()
    saved=conn.execute('SELECT payload FROM premium_exit_reports WHERE bucket=?',(key,)).fetchone()
    if saved:
        previous=json.loads(saved[0])
        if previous.get('fingerprint')==report['fingerprint']:
            return previous
    conn.execute('INSERT OR REPLACE INTO premium_exit_reports VALUES (?,?,?)',(key,report['updated_at'],json.dumps(report)))
    return report


def pair_report(*, samples, completed, settings, strategy, ticker, version, native_exits=None):
    """UI callers only read persisted results; the scheduled worker computes."""
    from config import get_user_data_dir
    from database import get_conn
    from strategy_health.context_orb_exit import PREMIUM_PROTOCOLS
    from config.research_universe import selected_tickers
    allowed=selected_tickers(settings)
    if allowed is not None and ticker not in allowed:
        return None
    account=settings.get('active_broker_account_id')
    mode='paper' if settings.get('paper_trading',True) else 'live'
    key=json.dumps([account,mode,strategy,ticker,version,VERSION,'research_control'],separators=(',',':'))
    if not BACKGROUND_ANALYSIS.get():
        with get_conn() as conn:
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='premium_exit_reports'").fetchone():
                return None
            row=conn.execute('SELECT payload FROM premium_exit_reports WHERE bucket=?',(key,)).fetchone()
            return json.loads(row[0]) if row else None
    reader=CaptureReader(get_user_data_dir()/'fast_capture'/'fast_capture.sqlite3')
    try:
        with get_conn() as conn:
            initialize(conn)
            seen=SEEN_KEYS.get()
            if seen is not None: seen.add(key)
            added=conn.execute('INSERT OR IGNORE INTO premium_exit_work(bucket,account,mode) VALUES (?,?,?)',(key,account,mode)).rowcount
            eligible=ANALYSIS_KEYS.get()
            if eligible is None:
                eligible={r[0] for r in conn.execute('SELECT bucket FROM premium_exit_work WHERE account IS ? AND mode=? ORDER BY last_run,bucket LIMIT 200',(account,mode))}
                ANALYSIS_KEYS.set(eligible)
            if added: eligible.add(key)
            if time.monotonic()>ANALYSIS_DEADLINE.get() or key not in eligible:
                row=conn.execute('SELECT payload FROM premium_exit_reports WHERE bucket=?',(key,)).fetchone()
                return json.loads(row[0]) if row else None
            conn.execute('UPDATE premium_exit_work SET last_run=? WHERE bucket=?',(time.time(),key))
            conn.commit()
            result=compare(conn,reader,samples=samples,completed=completed,
                account=account,mode=mode,
                strategy=strategy,ticker=ticker,version=version,partial=strategy in PREMIUM_PROTOCOLS,
                native_exits=native_exits)
            from config.research_order_specs import execution_id
            from config.strategy_catalog import REVIEWED_STRATEGIES
            from strategy_health.premium_native import baseline_spec, recorded_positions
            sid=execution_id(strategy,version,ticker)
            route=REVIEWED_STRATEGIES.get(sid)
            if route:
                expected=baseline_spec(settings,sid,ticker,route.version)
                entries,controls=recorded_positions(conn,account=account,mode=mode,sid=sid,ticker=ticker,
                                                    version=route.version,expected=expected)
                validation=compare(conn,reader,samples=entries,completed=controls,account=account,mode=mode,
                    strategy=sid,ticker=ticker,version=route.version,exact_baseline=expected)
                result={**result,'execution_validation':validation}
                conn.execute('UPDATE premium_exit_reports SET payload=? WHERE bucket=?',(json.dumps(result),key))
            from strategy_health.premium_publish import publish_report
            publish_report(get_user_data_dir()/'exit_lab.sqlite3',result.get('execution_validation',result))
            return result
    except TimeoutError:
        with get_conn() as conn:
            row=conn.execute('SELECT payload FROM premium_exit_reports WHERE bucket=?',(key,)).fetchone()
            return json.loads(row[0]) if row else None
    finally:
        reader.close()

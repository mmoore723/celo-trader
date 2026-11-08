"""Best-effort append-only exit evidence. Never evaluates or submits an order."""
from contextvars import ContextVar
from contextlib import closing
from datetime import datetime, timezone
from functools import wraps
import atexit
import json
import logging
import math
import os
from pathlib import Path
from queue import Queue, Full
import sqlite3
from threading import Thread, Lock
import time
from uuid import uuid4

_context = ContextVar('exit_trace_context', default=None)
_queue = Queue(maxsize=32)
_lock = Lock()
_thread = None
_stats = {}
_last_warning = 0.0


def _freeze(value, budget, issues, depth=0):
    budget[0] -= 1
    if budget[0] < 0 or depth > 12:
        issues.add('snapshot_limit'); return None
    if value is None or isinstance(value, (str, bool, int)):
        if isinstance(value, str) and len(value) > 200000:
            issues.add('string_limit'); return value[:200000]
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, datetime): return value.isoformat()
    if isinstance(value, dict):
        if len(value)>300: issues.add('mapping_limit')
        return {str(k): _freeze(v, budget, issues, depth+1) for k,v in list(value.items())[:300]
                if not any(s in str(k).lower() for s in ('password','secret','api_key','token'))}
    if isinstance(value, (tuple,list)):
        if len(value)>2500: issues.add('sequence_limit')
        return [_freeze(v,budget,issues,depth+1) for v in value[:2500]]
    if callable(value): return {'callable':getattr(value,'__qualname__',type(value).__name__), 'result':'logged_when_invoked'}
    # Freeze frames now, never hand mutable native state to the background thread.
    if type(value).__module__.startswith('pandas') and hasattr(value,'to_dict'):
        if len(value)>2500: issues.add('frame_limit')
        return {'type':'frame','rows':len(value), 'data':_freeze(value.iloc[-2500:].to_dict('split'),budget,issues,depth+1)}
    if type(value).__module__ in ('decimal','numpy') or type(value).__module__.startswith('numpy.'):
        return str(value)
    issues.add('unsupported_type:'+type(value).__name__)
    return {'type':type(value).__name__}


def snapshot(value):
    try:
        issues=set(); data=_freeze(value,[20000],issues)
        return {'data':data,'issues':sorted(issues),'complete':not issues}
    except Exception as exc:
        return {'data':None,'complete':False,'issues':['snapshot_failed:'+type(exc).__name__]}


def _warning():
    global _last_warning
    now=time.monotonic()
    if now-_last_warning>60:
        _last_warning=now
        try:
            logging.getLogger(__name__).warning('Exit decision capture incomplete; trading continues. Check exit_decisions/health.json.')
        except Exception: pass


def _write(root, event):
    root=Path(root); root.mkdir(parents=True,exist_ok=True,mode=0o700)
    import shutil
    if shutil.disk_usage(root).free<1024**3: raise OSError('capture_disk_reserve')
    with closing(sqlite3.connect(root/'decisions.sqlite3',timeout=.2)) as db, db:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('CREATE TABLE IF NOT EXISTS decisions (event_id TEXT PRIMARY KEY, cycle_id TEXT, recorded_at TEXT, account TEXT, mode TEXT, trade_id TEXT, strategy TEXT, ticker TEXT, payload TEXT)')
        trade=event['trade']
        db.execute('INSERT OR IGNORE INTO decisions VALUES (?,?,?,?,?,?,?,?,?)',
            (event['event_id'],event['cycle_id'],event['recorded_at'],trade.get('broker_account_id'),
             event['mode'],str(trade.get('id')),trade.get('strategy_id'),trade.get('ticker'),json.dumps(event,allow_nan=False)))


def _worker():
    while True:
        root,event=_queue.get()
        stats=_stats.setdefault(root,{'saved':0,'failed':0,'dropped':0})
        try:
            _write(root,event); stats['saved']+=1; stats['last_saved_at']=datetime.now(timezone.utc).isoformat()
        except Exception as exc:
            stats['failed']+=1; stats['last_error']=type(exc).__name__; _warning()
        finally:
            try:
                p=Path(root); p.mkdir(parents=True,exist_ok=True,mode=0o700)
                temp=p/('health.'+str(os.getpid())+'.tmp')
                temp.write_text(json.dumps(dict(stats,queue_depth=_queue.qsize(),updated_at=datetime.now(timezone.utc).isoformat())))
                os.replace(temp,p/'health.json')
            except Exception: _warning()
            _queue.task_done()


def _emit(stage, data):
    global _thread
    try:
        ctx=_context.get()
        if ctx is None or os.environ.get('CELO_EXIT_TRACE_DISABLED')=='1': return
        event=dict(ctx['identity'],event_id=str(uuid4()),recorded_at=datetime.now(timezone.utc).isoformat(),
                   stage=stage,evidence_type='native_decision_observation_not_fill',snapshot=data)
        if len(json.dumps(event,allow_nan=False))>512000:
            event['snapshot']={'complete':False,'issues':['event_size_limit'],'data':None}
        root=ctx['root']
        with _lock:
            if _thread is None or not _thread.is_alive():
                _thread=Thread(target=_worker,name='exit-decision-writer',daemon=True); _thread.start()
        try: _queue.put_nowait((root,event))
        except Full:
            _stats.setdefault(root,{'saved':0,'failed':0,'dropped':0})['dropped']+=1; _warning()
    except Exception:
        _warning()


def note(stage, value):
    try: _emit(stage,snapshot(value))
    except Exception: pass


def traced_call(name, function, *args, **kwargs):
    if _context.get() is None: return function(*args,**kwargs)
    before=snapshot({'args':args,'kwargs':kwargs})
    started=datetime.now(timezone.utc).isoformat()
    try:
        result=function(*args,**kwargs)
    except Exception as exc:
        note(name,{'started_at':started,'before':before,'error_type':type(exc).__name__})
        raise
    note(name,{'started_at':started,'before':before,'after':snapshot({'args':args,'kwargs':kwargs}),'result':result})
    return result


def decision(function):
    @wraps(function)
    def wrapped(*args,**kwargs): return traced_call(function.__module__+'.'+function.__name__,function,*args,**kwargs)
    return wrapped


def position_cycle(function):
    @wraps(function)
    def wrapped(alpaca,tradier,trade,balance):
        token=None
        try:
            if os.environ.get('CELO_EXIT_TRACE_DISABLED')!='1':
                from config.paths import get_user_data_dir
                from trading.state import get_user_state
                identity={k:trade.get(k) for k in ('id','broker_account_id','paper','strategy_id','ticker','contract_symbol','contracts','entry_time','entry_price','strategy_context_json')}
                identity=snapshot(identity)['data']
                token=_context.set({'root':str(get_user_data_dir(create=False)/'exit_decisions'),
                    'identity':{'cycle_id':str(uuid4()),'trade':identity,
                                'mode':'paper' if trade.get('paper') in (True,1) else 'live' if trade.get('paper') in (False,0) else 'unknown'}})
                note('cycle_start',get_user_state().get('positions',{}).get(trade.get('id'),{}))
        except Exception: _warning()
        try: return function(alpaca,tradier,trade,balance)
        finally:
            if token is not None:
                try:
                    from trading.state import get_user_state
                    note('cycle_end',get_user_state().get('positions',{}).get(trade.get('id'),{}))
                except Exception: _warning()
                _context.reset(token)
    return wrapped


def flush(timeout=2):
    end=time.monotonic()+timeout
    while _queue.unfinished_tasks and time.monotonic()<end: time.sleep(.01)
    return _queue.unfinished_tasks==0


atexit.register(flush)

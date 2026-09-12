"""Bounded observation of the six enabled native strategy decision paths.

This records which evaluators ran and what the router returned. It does NOT
claim complete market coverage, replayable inputs, option prices or fills.
It never calls a broker, changes a signal or enables a strategy.
"""
from datetime import datetime
from functools import lru_cache
import hashlib
import json
import logging
import os
from pathlib import Path
import sqlite3
import threading
from uuid import uuid4
import zlib

from auth.context import get_current_user_id
from config.paths import get_user_data_dir

PROTOCOL = 'enabled_native_decision_coverage_v1'
MAX_DATABASE_BYTES = 16 * 1024 * 1024
MAX_PAYLOAD_BYTES = 16 * 1024
PAIRS = {
    'V2_SPY_TREND_CONT': ('SPY',),
    'V2_SPY_AFTERNOON_FVG': ('SPY',),
    'V2_FAILED_OR_BREAK_VWAP_REVERSION': ('SPY',),
    'V2_ORB_PULLBACK': ('TSLA',),
    'V2_TSLA_TWO_LEG_TREND_PULLBACK': ('TSLA',),
    'CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG': ('AMZN', 'TSLA'),
}
_lock = threading.Lock()
_warned = set()
logger = logging.getLogger('celo_trader.native_coverage')


def warn(reason):
    key = (datetime.now().date(), reason)
    if key not in _warned:
        if len(_warned) > 32:
            _warned.clear()
        _warned.add(key)
        logger.warning('Native decision coverage unavailable: %s. Trading unchanged.', reason)


@lru_cache(maxsize=1)
def source_hashes():
    root = Path(__file__).resolve().parents[2]
    paths = ['strategy_router/route.py', 'strategy_router/evaluators.py',
             'trading/entry/injected_setups.py', 'trading/entry/tick.py',
             'trading/diagnostics/native_coverage.py']
    return {name: hashlib.sha256((root/name).read_bytes()).hexdigest() for name in paths}


def append(payload, path):
    raw = json.dumps(payload, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    if len(raw) > MAX_PAYLOAD_BYTES:
        raise ValueError('payload_budget')
    packed = zlib.compress(raw)
    path = Path(path)
    if path.is_symlink():
        raise ValueError('symlink_path')
    try:
        fd = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, 0o600)
        os.close(fd)
    except FileExistsError:
        pass
    with _lock:
        conn = sqlite3.connect(str(path), timeout=.05)
        try:
            conn.execute('PRAGMA journal_mode=DELETE')
            conn.execute('PRAGMA synchronous=FULL')
            size = conn.execute('PRAGMA page_size').fetchone()[0]
            conn.execute(f'PRAGMA max_page_count={MAX_DATABASE_BYTES // size}')
            conn.execute('''CREATE TABLE IF NOT EXISTS coverage (
                id INTEGER PRIMARY KEY, account_digest TEXT NOT NULL, paper INTEGER NOT NULL,
                evaluated_at TEXT NOT NULL, payload_sha256 TEXT NOT NULL, payload BLOB NOT NULL)''')
            used = conn.execute('PRAGMA page_count').fetchone()[0] * size
            if used + len(packed) + 1024 * 1024 > MAX_DATABASE_BYTES:
                raise ValueError('storage_budget_reached')
            conn.execute('INSERT INTO coverage(account_digest,paper,evaluated_at,payload_sha256,payload) VALUES (?,?,?,?,?)',
                (payload['account_digest'], int(payload['paper']), payload['evaluated_at'],
                 hashlib.sha256(raw).hexdigest(), packed))
            conn.commit()
        finally:
            conn.close()


class Coverage:
    def __init__(self, payload):
        self.payload = payload

    def observe(self, strategy_id, status, phase):
        if strategy_id not in self.payload['strategies'] or phase not in {'evaluation', 'routing'}:
            return
        record = self.payload['strategies'][strategy_id]
        if len(record['events']) >= 16:
            raise ValueError('event_budget')
        # Store no references to mutable evaluator or router objects.
        record['events'].append(dict(phase=phase, status=str(status)[:96]))
        record[phase] = str(status)[:96]

    def finish(self, signals, *, error=None):
        try:
            returned = []
            for signal in signals:
                if signal.strategy_id not in self.payload['strategies']:
                    continue
                meta = signal.meta if isinstance(signal.meta, dict) else {}
                returned.append(dict(strategy_id=signal.strategy_id, direction=str(signal.direction)[:24],
                    trigger=str(signal.trigger_bar)[:64],
                    candidate_id=str(meta.get('shadow_candidate_id') or '')[:128]))
            self.payload.update(returned=returned, completed_at=datetime.now().astimezone().isoformat(),
                                error=error)
            append(self.payload, get_user_data_dir(create=False)/'native_decision_coverage.sqlite3')
        except Exception as exc:
            warn(str(exc) if isinstance(exc, ValueError) else type(exc).__name__)


def begin(ticker, enabled, injected_statuses, frame, *, settings, now):
    """One small record per native ticker pass, with no extra market requests."""
    try:
        ticker = str(ticker).strip().upper()
        selected = sorted(sid for sid in enabled if ticker in PAIRS.get(sid, ()))
        account = settings.get('active_broker_account_id')
        if (not selected or not account or get_current_user_id() == 'system' or
                not isinstance(settings.get('paper_trading'), bool)):
            return None
        states = {sid:dict(evaluation=str(injected_statuses.get(sid, 'not_recorded')),
                           routing='not_recorded', events=[]) for sid in selected}
        # This summary is not a substitute for the exact as-of candle tape.
        clocks = frame['time'] if 'time' in frame.columns else None
        payload = dict(protocol=PROTOCOL, pass_id=str(uuid4()), ticker=ticker,
            account_digest=hashlib.sha256(str(account).encode()).hexdigest(), paper=settings['paper_trading'],
            evaluated_at=now.isoformat(), strategies=states,
            input_summary=dict(rows=len(frame), first=str(clocks.iloc[0]) if clocks is not None and len(clocks) else None,
                               last=str(clocks.iloc[-1]) if clocks is not None and len(clocks) else None),
            sources=source_hashes(), complete_replay_inputs=False, full_session_coverage=False,
            order_or_fill_confirmation=False)
        return Coverage(payload)
    except Exception as exc:
        warn(type(exc).__name__)
        return None

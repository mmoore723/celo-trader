"""Bounded, append-only evidence for enabled native TSLA ORB evaluations.

Not used for routing. Failure to record never changes a trading decision.
The dedicated database stops accepting records at its budget; it never prunes
existing evidence. An operator must archive it before capture can resume.
"""
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, time
from functools import lru_cache
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import sqlite3
import threading
import zlib

import pandas as pd

from auth.context import get_current_user_id
from config.paths import get_user_data_dir

PROTOCOL = 'native_tsla_orb_evaluation_v1'
MAX_DATABASE_BYTES = 64 * 1024 * 1024
MAX_PAYLOAD_BYTES = 256 * 1024
MAX_ROWS = 512
COLUMNS = ('time', 'open', 'high', 'low', 'close', 'volume', 'rvol')
_lock = threading.Lock()
_warned = set()
logger = logging.getLogger('celo_trader.orb_evidence')


def encode(value):
    if isinstance(value, (datetime, pd.Timestamp)):
        return {'__time__': value.isoformat()}
    if isinstance(value, float) and not math.isfinite(value):
        return {'__float__': str(value)}
    if isinstance(value, dict):
        return {str(k): encode(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [encode(v) for v in value]
    if hasattr(value, 'item'):
        return encode(value.item())
    return value


def decode(value):
    if isinstance(value, dict):
        if set(value) == {'__time__'}:
            return pd.Timestamp(value['__time__'])
        if set(value) == {'__float__'}:
            return float(value['__float__'])
        return {k: decode(v) for k, v in value.items()}
    return [decode(v) for v in value] if isinstance(value, list) else value


def canonical(value):
    return json.dumps(encode(value), sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


@lru_cache(maxsize=1)
def source_hashes():
    root = Path(__file__).resolve().parents[2]
    paths = ['trading/orb_retouch_execution.py', 'strategies/market_structure.py',
             'strategies/price_action_context.py', 'strategies/base/__init__.py',
             'strategies/base/signal.py', 'trading/diagnostics/orb_evidence.py']
    return {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths}


def warn(reason):
    # At most one warning per reason per day and process. No account identifiers.
    key = (datetime.now().date(), reason)
    if key not in _warned:
        _warned.clear() if len(_warned) > 32 else None
        _warned.add(key)
        logger.warning('ORB decision evidence unavailable: %s. Trading behavior unchanged.', reason)


def begin(state, frame, *, now, price, quote, settings):
    """Capture input copies, including forming bars used by signal metadata.

    The native evaluator itself excludes unfinished bars from breakout logic.
    Receipt/evaluation time is never substituted for a missing quote timestamp.
    """
    try:
        if not time(9, 30) <= now.time().replace(tzinfo=None) <= time(10, 30):
            return None
        account = settings.get('active_broker_account_id')
        if not account or get_current_user_id() == 'system':
            return None
        if len(frame) > MAX_ROWS or frame.columns.duplicated().any():
            raise ValueError('input_size_or_columns')
        cols = [c for c in COLUMNS if c in frame.columns]
        return dict(protocol=PROTOCOL, scope='enabled_native_execution', ticker='TSLA',
                    account_digest=hashlib.sha256(str(account).encode()).hexdigest(),
                    paper=settings.get('paper_trading'), evaluated_at=now,
                    quote={k: (quote or {}).get(k) for k in ('t', 'bp', 'ap', 'bs', 'as')},
                    quote_price=price, state_before=deepcopy(state),
                    frame=dict(columns=cols, data=deepcopy(frame[cols].values.tolist())),
                    pandas_version=pd.__version__, sources=source_hashes())
    except Exception as exc:
        warn(type(exc).__name__)
        return None


def append(payload, path):
    """Store one independently compressed record, no pruning or unbounded WAL."""
    raw = canonical(payload)
    if len(raw) > MAX_PAYLOAD_BYTES:
        raise ValueError('payload_budget')
    packed = zlib.compress(raw)
    path = Path(path)
    if path.is_symlink():
        raise ValueError('symlink_path')
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        os.close(fd)
    except FileExistsError:
        pass
    with _lock:
        conn = sqlite3.connect(str(path), timeout=.05)
        try:
            conn.execute('PRAGMA journal_mode=DELETE')
            conn.execute('PRAGMA synchronous=FULL')
            page_size = conn.execute('PRAGMA page_size').fetchone()[0]
            conn.execute(f'PRAGMA max_page_count={MAX_DATABASE_BYTES // page_size}')
            conn.execute('''CREATE TABLE IF NOT EXISTS evaluations (
                id INTEGER PRIMARY KEY, recorded_at TEXT NOT NULL,
                account_digest TEXT NOT NULL, paper INTEGER NOT NULL,
                payload_sha256 TEXT NOT NULL, payload BLOB NOT NULL)''')
            used = conn.execute('PRAGMA page_count').fetchone()[0] * page_size
            # Reserve transaction overhead as well as the compressed row.
            if used + len(packed) + 1024 * 1024 > MAX_DATABASE_BYTES:
                raise ValueError('storage_budget_reached')
            if not isinstance(payload['paper'], bool):
                raise ValueError('unknown_trading_mode')
            conn.execute('INSERT INTO evaluations(recorded_at,account_digest,paper,payload_sha256,payload) VALUES (?,?,?,?,?)',
                         (datetime.now().astimezone().isoformat(), payload['account_digest'], int(payload['paper']),
                          hashlib.sha256(raw).hexdigest(), packed))
            conn.commit()
        finally:
            conn.close()


def finish(payload, state, signal, status, *, error=None):
    if payload is None:
        return
    try:
        payload.update(state_after=deepcopy(state), signal=asdict(signal) if signal else None,
                       status=status, error=error)
        append(payload, get_user_data_dir(create=False) / 'orb_decision_evidence.sqlite3')
    except Exception as exc:
        warn(str(exc) if isinstance(exc, ValueError) else type(exc).__name__)

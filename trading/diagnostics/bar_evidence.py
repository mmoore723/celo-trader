"""Bounded, observational inputs for the four enabled bar-evaluator paths.

No strategy or router rules change. Clock-bracket ambiguity is retained and
rejected by replay. History chunks are content-addressed in the existing
64 MiB evidence database, never duplicated once per strategy/pass.
"""
from copy import deepcopy
from dataclasses import asdict
from functools import lru_cache
import hashlib
import importlib
from pathlib import Path

import pandas as pd

from auth.context import get_current_user_id
from config.paths import get_user_data_dir
from trading.diagnostics import orb_evidence as storage

PROTOCOL = 'native_bar_evaluation_v1'
SPECS = {
    'V2_SPY_TREND_CONT': ('strategies.spy_trend_continuation_v2', 'evaluate', ('SPY',),
                        ('_emitted_trigger_by_session', '_active_breakout_by_session')),
    'V2_SPY_AFTERNOON_FVG': ('strategies.spy_afternoon_fvg_v2', 'evaluate', ('SPY',),
                          ('_emitted_trigger_by_session',)),
    'V2_FAILED_OR_BREAK_VWAP_REVERSION': ('strategies.spy_failed_range_recovery_v2', 'evaluate', ('SPY',),
                                        ('_emitted_trigger_by_session',)),
    'CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG': ('strategies.context_strategy_observers',
                                              'evaluate_vwap_displacement', ('AMZN', 'TSLA'), ('_emitted',)),
}
MAX_HISTORY_ROWS = 20000
MAX_STATE_ITEMS = 2048


def clock():
    return pd.Timestamp.now(tz='America/New_York')


@lru_cache(maxsize=1)
def source_hashes():
    root = Path(__file__).resolve().parents[2]
    paths = {spec[0].replace('.', '/') + '.py' for spec in SPECS.values()}
    paths.update(('strategies/market_structure.py', 'strategies/price_action_context.py',
                  'strategies/base/__init__.py', 'strategies/base/signal.py',
                  'trading/diagnostics/bar_evidence.py', 'trading/diagnostics/orb_evidence.py'))
    return {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in sorted(paths)}


def scoped_state(namespace, names, owner, ticker):
    result = {}
    for name in names:
        value = namespace[name]
        # Never retain another user's cache or their identifiers. Avoid live
        # iteration while another account's thread can mutate the container.
        selected = [(tuple(key[1:]), item) for key, item in value.copy().items()
                    if key[0] == owner and key[1] == ticker] if isinstance(value, dict) else [
                        tuple(key[1:]) for key in value.copy() if key[0] == owner and key[1] == ticker]
        if len(selected) > MAX_STATE_ITEMS:
            raise ValueError('state_budget')
        selected.sort(key=repr)
        result[name] = dict(kind='dict' if isinstance(value, dict) else 'set', entries=deepcopy(selected))
    return result


class Recorder:
    def __init__(self, settings):
        self.settings = settings

    def begin(self, strategy_id, frame, ticker, fn):
        try:
            spec = SPECS.get(strategy_id)
            owner = get_current_user_id()
            account = self.settings.get('active_broker_account_id')
            if (not spec or ticker not in spec[2] or owner == 'system' or not account
                    or not isinstance(self.settings.get('paper_trading'), bool)):
                return None
            module = importlib.import_module(spec[0])
            if fn is not getattr(module, spec[1]):
                return None
            if len(frame) > storage.MAX_ROWS or frame.columns.duplicated().any():
                raise ValueError('input_budget')
            columns = [c for c in storage.COLUMNS if c in frame.columns]
            inputs = dict(columns=columns, dtypes=[str(frame[c].dtype) for c in columns],
                          data=deepcopy(frame[columns].values.tolist()), history=[])
            blobs = {}
            def remember(value):
                raw = storage.canonical(value)
                if len(raw) > storage.MAX_PAYLOAD_BYTES:
                    raise ValueError('input_blob_budget')
                digest = hashlib.sha256(raw).hexdigest()
                blobs[digest] = raw
                return digest
            if strategy_id.startswith('CTX_'):
                history = frame.attrs.get('multi_session_bars')
                if history is not None and not isinstance(history, tuple):
                    raise ValueError('unsupported_history_type')
                if history:
                    if len(history) > MAX_HISTORY_ROWS:
                        raise ValueError('history_budget')
                    inputs['history'] = [remember(history[i:i+128]) for i in range(0, len(history), 128)]
            input_digest = remember(inputs)
            before = scoped_state(vars(module), spec[3], owner, ticker)
            payload = dict(protocol=PROTOCOL, strategy_id=strategy_id, ticker=ticker,
                           scope='enabled_native_execution', account_digest=hashlib.sha256(str(account).encode()).hexdigest(),
                           paper=self.settings['paper_trading'], state_before=before, input_digest=input_digest,
                           sources=source_hashes(), pandas_version=pd.__version__, evaluated_at=clock())
            return payload, blobs, module, owner
        except Exception as exc:
            storage.warn('bar_' + type(exc).__name__)
            return None

    def finish(self, ticket, signal, *, error=None):
        if ticket is None:
            return
        try:
            finished = clock()
            payload, blobs, module, owner = ticket
            payload.update(finished_at=finished,
                           state_after=scoped_state(vars(module), SPECS[payload['strategy_id']][3], owner, payload['ticker']),
                           signal=asdict(signal) if signal else None, error=error)
            storage.append(payload, get_user_data_dir(create=False) / 'orb_decision_evidence.sqlite3',
                           table='bar_evaluations', blobs=blobs)
        except Exception as exc:
            storage.warn('bar_' + (str(exc) if isinstance(exc, ValueError) else type(exc).__name__))

"""Native Two-Leg inputs and state transitions; no order or research authority.

Shares the existing ORB database budget, in a separate protocol-specific table.
The caller only captures enabled TSLA execution, never research observations.
"""
from copy import deepcopy
from dataclasses import asdict
from datetime import time
from functools import lru_cache
import hashlib
from pathlib import Path

import pandas as pd

from auth.context import get_current_user_id
from config.paths import get_user_data_dir
from trading.diagnostics import orb_evidence as storage

PROTOCOL = 'native_tsla_two_leg_evaluation_v1'
STRATEGY_ID = 'V2_TSLA_TWO_LEG_TREND_PULLBACK'


@lru_cache(maxsize=1)
def source_hashes():
    root = Path(__file__).resolve().parents[2]
    paths = ['trading/two_leg_trend_pullback_execution.py',
             'strategies/price_action_context.py', 'strategies/base/__init__.py',
             'strategies/base/signal.py', 'trading/diagnostics/two_leg_evidence.py',
             'trading/diagnostics/orb_evidence.py']
    return {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths}


def begin(state, frame, *, now, settings):
    try:
        # Include the first evaluation after the last eligible 11:30 candle.
        # Outside this interval capture absence is not called a no-setup result.
        if not time(9, 30) <= now.time().replace(tzinfo=None) <= time(11, 32):
            return None
        account = settings.get('active_broker_account_id')
        if not account or get_current_user_id() == 'system' or not isinstance(settings.get('paper_trading'), bool):
            return None
        if len(frame) > storage.MAX_ROWS or frame.columns.duplicated().any():
            raise ValueError('input_size_or_columns')
        cols = [c for c in storage.COLUMNS if c in frame.columns]
        return dict(protocol=PROTOCOL, strategy_id=STRATEGY_ID,
                    scope='enabled_native_execution', ticker='TSLA',
                    account_digest=hashlib.sha256(str(account).encode()).hexdigest(),
                    paper=settings['paper_trading'], evaluated_at=now,
                    state_before=deepcopy(state),
                    frame=dict(columns=cols, data=deepcopy(frame[cols].values.tolist())),
                    pandas_version=pd.__version__, sources=source_hashes())
    except Exception as exc:
        storage.warn('two_leg_' + type(exc).__name__)
        return None


def finish(payload, state, signal, status, *, error=None):
    if payload is None:
        return
    try:
        payload.update(state_after=deepcopy(state), signal=asdict(signal) if signal else None,
                       status=status, error=error)
        storage.append(payload, get_user_data_dir(create=False) / 'orb_decision_evidence.sqlite3',
                       table='two_leg_evaluations')
    except Exception as exc:
        storage.warn('two_leg_' + (str(exc) if isinstance(exc, ValueError) else type(exc).__name__))

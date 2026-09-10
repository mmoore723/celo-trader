"""Measure Compression's frozen exits on completed one-minute candles."""
from dataclasses import asdict
from datetime import time
from functools import lru_cache
import hashlib
import inspect

from research.engine.strategies.afternoon_compression_breakout import (
    AfternoonCompressionBreakout, AfternoonCompressionBreakoutConfig,
)
from research.engine.strategies.trend_continuation import _atr, _ema
from research.engine.strategies.vwap_pullback import _session, _vwaps
from strategy_health.impulse_exit import et, first_exit as structural_exit

STRATEGY_ID = 'V2_AFTERNOON_COMPRESSION_BREAKOUT'
PROTOCOL = 'compression_structural_2r_completed1m_intraday_v1'


def research_config():
    # Match the deployed wider-baseline entry, not the class defaults.
    return AfternoonCompressionBreakoutConfig(max_compression_pct=.004, entry_end=time(15))


@lru_cache(maxsize=1)
def engine_hash():
    source='\n'.join(inspect.getsource(x) for x in (
        AfternoonCompressionBreakout, AfternoonCompressionBreakoutConfig, _atr, _ema, _session, _vwaps,
    ))
    return hashlib.sha256(source.encode()).hexdigest()


def entry_state(strategy):
    return {'engine_hash':engine_hash(),
            'config':{k:v.isoformat() if isinstance(v,time) else v for k,v in asdict(strategy.config).items()},
            'session_policy':'completed1m_stop_target_or_close_1600_v1'}


def first_exit(frame, *, seed, **kwargs):
    if seed != entry_state(AfternoonCompressionBreakout(research_config())):
        return et(kwargs['entry_at']),'missing_exit_state'
    # No arbitrary 75-bar timer: the original entry supplies only stop/target.
    # 390 exceeds every remaining intraday window; 16:00 is the explicit fallback.
    return structural_exit(frame, **kwargs, timeframe_minutes=1, max_hold_bars=390)

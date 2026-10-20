"""Measure Compression's frozen exits on completed one-minute candles."""
from dataclasses import asdict
from datetime import time, timedelta
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


def first_exit(frame, *, seed, repair_lookup=None, **kwargs):
    if seed != entry_state(AfternoonCompressionBreakout(research_config())):
        return et(kwargs['entry_at']),'missing_exit_state'
    # No arbitrary 75-bar timer: the original entry supplies only stop/target.
    # 390 exceeds every remaining intraday window; 16:00 is the explicit fallback.
    event = structural_exit(frame, **kwargs, timeframe_minutes=1, max_hold_bars=390)
    if (event is not None and event[1] != 'missing_bars') or repair_lookup is None:
        return event
    try:
        entry, now = et(kwargs['entry_at']), et(kwargs['now'])
        end = min(now.replace(second=0, microsecond=0), entry.replace(hour=16, minute=0))
        expected = set()
        stamp = entry + timedelta(minutes=1)
        while stamp < end:
            expected.add(stamp)
            stamp += timedelta(minutes=1)
        if expected.issubset(et(value) for value in frame['time']):
            return event
        replacement = repair_lookup()
        stamps = [et(value) for value in replacement['time']]
        if len(stamps) != len(set(stamps)) or not expected.issubset(stamps):
            return event
        repaired = structural_exit(replacement, **kwargs, timeframe_minutes=1, max_hold_bars=390)
        if repaired is None or repaired[1] in {'underlying_stop', 'underlying_2r_target', 'session_flatten', 'end_of_available_session'}:
            return repaired
    except Exception:
        pass
    return event

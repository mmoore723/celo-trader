"""Generic Trend Continuation's original structural exit, never SPY execution."""
from dataclasses import asdict
from functools import lru_cache
import hashlib
import inspect

from research.engine.simulator import Simulator, SimulationConfig
from research.engine.strategies.trend_continuation import (
    TrendContinuation, TrendContinuationConfig, _atr, _ema,
)
from strategy_health.impulse_exit import et, first_exit as structural_exit

STRATEGY_ID = "V2_TREND_CONT"
PROTOCOL = "trend_cont_structural_2r_75bars_completed5m_v1"


@lru_cache(maxsize=1)
def engine_hash():
    source = '\n'.join(inspect.getsource(x) for x in (
        TrendContinuation, TrendContinuationConfig, _atr, _ema, Simulator, SimulationConfig,
    ))
    return hashlib.sha256(source.encode()).hexdigest()


def entry_state(strategy):
    # No recursive exit indicator: the entry's stop/target are already frozen
    # in candidate metadata. Pin the exact source and configuration as proof.
    return {'engine_hash': engine_hash(), 'config': asdict(strategy.config)}


def first_exit(frame, *, seed, **kwargs):
    if (not isinstance(seed, dict) or seed.get('engine_hash') != engine_hash()
            or seed.get('config') != asdict(TrendContinuationConfig())):
        return et(kwargs['entry_at']), 'missing_exit_state'
    return structural_exit(frame, **kwargs, max_hold_bars=75, time_cap_reason='time_cap_75bars')

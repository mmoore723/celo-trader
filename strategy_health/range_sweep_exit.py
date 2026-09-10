"""Observe the call setup's original sweep stop and frozen entry VWAP."""
from dataclasses import asdict
from datetime import time
from functools import lru_cache
import hashlib
import inspect

from research.engine.strategies.range_sweep_reclaim import (
    RangeSweepReclaim, RangeSweepReclaimConfig, efficiency_ratio,
)
from research.engine.strategies.trend_continuation import _atr
from research.engine.strategies.vwap_pullback import _session, _vwaps
from strategy_health.impulse_exit import et, first_exit as structural_exit

STRATEGY_ID = 'V2_RANGE_SWEEP_RECLAIM'
PROTOCOL = 'range_sweep_frozen_vwap_completed1m_intraday_v1'


def research_config():
    return RangeSweepReclaimConfig(range_bars=30, maximum_efficiency=.30, minimum_sweep_atr=.15)


@lru_cache(maxsize=1)
def engine_hash():
    source='\n'.join(inspect.getsource(x) for x in (
        RangeSweepReclaim, RangeSweepReclaimConfig, efficiency_ratio, _atr, _session, _vwaps,
    ))
    return hashlib.sha256(source.encode()).hexdigest()


def entry_state(strategy):
    return {'engine_hash':engine_hash(),
            'config':{k:v.isoformat() if isinstance(v,time) else v for k,v in asdict(strategy.config).items()},
            'session_policy':'completed1m_frozen_vwap_or_close_1600_v1'}


def first_exit(frame, *, seed, **kwargs):
    if seed != entry_state(RangeSweepReclaim(research_config())):
        return et(kwargs['entry_at']),'missing_exit_state'
    # The deployed research adapter exposes calls only; reject mismatched evidence.
    if kwargs['direction'] != 'bullish':
        return et(kwargs['entry_at']),'invalid_levels'
    event=structural_exit(frame, **kwargs, timeframe_minutes=1, max_hold_bars=390)
    if event and event[1]=='underlying_2r_target':
        return event[0],'underlying_vwap_target'
    return event

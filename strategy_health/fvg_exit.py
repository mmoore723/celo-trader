"""Generic FVG structural-exit evidence, separate from tradable SPY FVG."""
from dataclasses import asdict
from functools import lru_cache
import hashlib
import inspect

from research.engine.simulator import Simulator, SimulationConfig
from research.engine.strategies.fair_value_gap import FairValueGap, FairValueGapConfig
from research.engine.strategies.vwap_pullback import _session, _vwaps
from research.engine.strategies.trend_continuation import _atr, _ema
from strategy_health.impulse_exit import et, first_exit as structural_exit

STRATEGY_ID = 'V2_FAIR_VALUE_GAP'
PROTOCOL = 'fvg_structural_2r_75bars_rth_completed5m_v1'


@lru_cache(maxsize=1)
def engine_hash():
    source = '\n'.join(inspect.getsource(x) for x in (
        FairValueGap, FairValueGapConfig, _session, _vwaps, _atr, _ema, Simulator, SimulationConfig,
    ))
    return hashlib.sha256(source.encode()).hexdigest()


def entry_state(strategy):
    return {'engine_hash': engine_hash(), 'config': asdict(strategy.config)}


def first_exit(frame, *, seed, **kwargs):
    if (not isinstance(seed, dict) or seed.get('engine_hash') != engine_hash()
            or seed.get('config') != asdict(FairValueGapConfig())):
        return et(kwargs['entry_at']), 'missing_exit_state'
    return structural_exit(frame, **kwargs, max_hold_bars=75, time_cap_reason='time_cap_75bars')

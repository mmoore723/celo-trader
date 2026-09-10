"""Generic VWAP Pullback's structural-exit research observer, never orders."""
from dataclasses import asdict
from functools import lru_cache
import hashlib
import inspect

from research.engine.simulator import Simulator, SimulationConfig
from research.engine.strategies.vwap_pullback import VWAPPullback, VWAPPullbackConfig, _session, _vwaps
from research.engine.strategies.trend_continuation import _atr, _ema
from strategy_health.impulse_exit import et, first_exit as structural_exit

STRATEGY_ID = "V2_VWAP_PULLBACK"
PROTOCOL = "vwap_pullback_structural_2r_75bars_rth_completed5m_v1"


@lru_cache(maxsize=1)
def engine_hash():
    source = '\n'.join(inspect.getsource(x) for x in (
        VWAPPullback, VWAPPullbackConfig, _session, _vwaps, _atr, _ema, Simulator, SimulationConfig,
    ))
    return hashlib.sha256(source.encode()).hexdigest()


def entry_state(strategy):
    return {'engine_hash': engine_hash(), 'config': asdict(strategy.config)}


def first_exit(frame, *, seed, **kwargs):
    # Preserve the signal's original levels; no VWAP recalculation or trailing
    # stop can silently replace them after the option entry has been recorded.
    if (not isinstance(seed, dict) or seed.get('engine_hash') != engine_hash()
            or seed.get('config') != asdict(VWAPPullbackConfig())):
        return et(kwargs['entry_at']), 'missing_exit_state'
    return structural_exit(frame, **kwargs, max_hold_bars=75, time_cap_reason='time_cap_75bars')

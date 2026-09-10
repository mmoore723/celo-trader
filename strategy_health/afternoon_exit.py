"""Original Afternoon Reversal exit evidence; no order or entry-rule changes."""
from dataclasses import asdict
from datetime import time
from functools import lru_cache
import hashlib
import inspect

from research.engine.simulator import Simulator, SimulationConfig
from research.engine.strategies.afternoon_reversal import AfternoonReversal, AfternoonReversalConfig, _confirmed_swings
from research.engine.strategies.vwap_pullback import _session, _vwaps
from research.engine.strategies.trend_continuation import _atr
from strategy_health.impulse_exit import et, first_exit as structural_exit

STRATEGY_ID = 'V2_AFTERNOON_REVERSAL'
PROTOCOL = 'afternoon_reversal_structural_2r_75bars_rth_completed5m_v1'


@lru_cache(maxsize=1)
def engine_hash():
    source = '\n'.join(inspect.getsource(x) for x in (
        AfternoonReversal, AfternoonReversalConfig, _confirmed_swings,
        _session, _vwaps, _atr, Simulator, SimulationConfig,
    ))
    return hashlib.sha256(source.encode()).hexdigest()


def config_proof(config):
    # Store identical primitive values before and after the metadata JSON round trip.
    return {k: v.isoformat() if isinstance(v, time) else v for k,v in asdict(config).items()}


def entry_state(strategy):
    return {'engine_hash': engine_hash(), 'config': config_proof(strategy.config)}


def first_exit(frame, *, seed, **kwargs):
    if (not isinstance(seed, dict) or seed.get('engine_hash') != engine_hash()
            or seed.get('config') != config_proof(AfternoonReversalConfig())):
        return et(kwargs['entry_at']), 'missing_exit_state'
    return structural_exit(frame, **kwargs, max_hold_bars=75, time_cap_reason='time_cap_75bars')

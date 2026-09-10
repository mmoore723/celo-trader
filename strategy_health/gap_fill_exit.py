"""Gap Fill's frozen ATR exit, plus an explicitly separate short-anchor test.

The observation loop matches Opening Momentum's simulator mechanics. Only
Gap Fill's own engine/state is restored; their fingerprints cannot mix.
"""
from functools import lru_cache
import hashlib
import inspect

from research.engine.simulator import Simulator, SimulationConfig
from research.engine.strategies.gap_fill_rth import GapFillRTH, GapFillRTHConfig, _atr
from strategy_health import momentum_exit

STRATEGY_ID = "V2_GAP_FILL_RTH"
PROTOCOL = "gap_fill_2atr_5m_trail_1m_observation_v1"
LOW_WATER_PROTOCOL = "gap_fill_2atr_short_low_water_1m_observation_v1"


@lru_cache(maxsize=1)
def engine_hash():
    source = '\n'.join(inspect.getsource(x) for x in (
        GapFillRTH, GapFillRTHConfig, _atr, Simulator, SimulationConfig,
    ))
    return hashlib.sha256(source.encode()).hexdigest()


def entry_state(strategy):
    return momentum_exit.entry_state(strategy, fingerprint=engine_hash())


def restored(seed, entry):
    return momentum_exit.restored(seed, entry, engine_factory=GapFillRTH, fingerprint=engine_hash())


def first_exit(frame, **kwargs):
    return momentum_exit.first_exit(frame, **kwargs, restore_engine=restored, strategy_id=STRATEGY_ID)

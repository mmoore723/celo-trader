"""Confirmed ORB's original 1.5R structural exit, observation only."""
from dataclasses import asdict
from datetime import time
from functools import lru_cache
import hashlib
import inspect

from research.engine.simulator import Simulator, SimulationConfig
from research.engine.strategies.opening_range_breakout import OpeningRangeBreakout, OpeningRangeBreakoutConfig
from research.engine.strategies.vwap_pullback import _session
from strategy_health.impulse_exit import et, first_exit as structural_exit

STRATEGY_ID = 'V2_ORB_CONFIRMED_BREAKOUT'
PROTOCOL = 'orb_confirmed_structural_1_5r_75bars_rth_completed5m_v1'


@lru_cache(maxsize=1)
def engine_hash():
    source='\n'.join(inspect.getsource(x) for x in (
        OpeningRangeBreakout,OpeningRangeBreakoutConfig,_session,Simulator,SimulationConfig,
    ))
    return hashlib.sha256(source.encode()).hexdigest()


def config_proof(config):
    return {k:v.isoformat() if isinstance(v,time) else v for k,v in asdict(config).items()}


def entry_state(strategy):
    return {'engine_hash':engine_hash(),'config':config_proof(strategy.config)}


def first_exit(frame, *, seed, **kwargs):
    if (not isinstance(seed,dict) or seed.get('engine_hash') != engine_hash()
            or seed.get('config') != config_proof(OpeningRangeBreakoutConfig())):
        return et(kwargs['entry_at']),'missing_exit_state'
    event=structural_exit(frame,**kwargs,max_hold_bars=75,time_cap_reason='time_cap_75bars')
    # The shared observer compares the exact frozen price, not a reward ratio.
    # Its legacy 2R reason must not mislabel this strategy's 1.5R target.
    if event and event[1]=='underlying_2r_target':
        return event[0],'underlying_1_5r_target'
    return event

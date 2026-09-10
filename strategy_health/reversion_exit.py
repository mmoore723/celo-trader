"""Observe VWAP Reversion's frozen entry levels; never place orders."""
from dataclasses import asdict
from datetime import time
from functools import lru_cache
import hashlib
import inspect

from research.engine.simulator import Simulator, SimulationConfig
from research.engine.strategies.vwap_reversion_rth import VWAPReversionRTH, VWAPReversionRTHConfig
from research.engine.strategies.vwap_pullback import _session, _vwaps
from research.engine.strategies.trend_continuation import _atr, _ema
from strategy_health.impulse_exit import et, first_exit as structural_exit

STRATEGY_ID = 'V2_VWAP_REVERSION_RTH'
PROTOCOL = 'vwap_reversion_frozen_vwap_4atr_75bars_rth_completed5m_v1'


@lru_cache(maxsize=1)
def engine_hash():
    source='\n'.join(inspect.getsource(x) for x in (
        VWAPReversionRTH,VWAPReversionRTHConfig,_session,_vwaps,_atr,_ema,Simulator,SimulationConfig,
    ))
    return hashlib.sha256(source.encode()).hexdigest()


def config_proof(config):
    return {k:v.isoformat() if isinstance(v,time) else v for k,v in asdict(config).items()}


def entry_state(strategy):
    return {'engine_hash':engine_hash(),'config':config_proof(strategy.config)}


def first_exit(frame, *, seed, **kwargs):
    if (not isinstance(seed,dict) or seed.get('engine_hash') != engine_hash()
            or seed.get('config') != config_proof(VWAPReversionRTHConfig())):
        return et(kwargs['entry_at']),'missing_exit_state'
    event=structural_exit(frame,**kwargs,max_hold_bars=75,time_cap_reason='time_cap_75bars')
    # The shared observer compares the supplied frozen price, not a fixed R multiple.
    if event and event[1]=='underlying_2r_target':
        return event[0],'underlying_vwap_target'
    return event

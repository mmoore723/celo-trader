"""EMA Pullback's 15-minute structural exits with an explicit RTH close correction."""
from dataclasses import asdict
from datetime import time
from functools import lru_cache
import hashlib
import inspect

from research.engine.simulator import Simulator, SimulationConfig
from research.engine.strategies.ema_pullback_rth import EMAPullbackRTH, EMAPullbackRTHConfig
from strategy_health.impulse_exit import et, first_exit as structural_exit

STRATEGY_ID = 'V2_EMA_PULLBACK_RTH'
PROTOCOL = 'ema_structural_2_06r_completed15m_rth_close_corrected_v1'


@lru_cache(maxsize=1)
def engine_hash():
    source='\n'.join(inspect.getsource(x) for x in (
        EMAPullbackRTH,EMAPullbackRTHConfig,Simulator,SimulationConfig,
    ))
    return hashlib.sha256(source.encode()).hexdigest()


def config_proof(config):
    return {k:v.isoformat() if isinstance(v,time) else v for k,v in asdict(config).items()}


def entry_state(strategy):
    return {'engine_hash':engine_hash(),'config':config_proof(strategy.config),
            'timeframe_minutes':15,'session_policy':'final_15m_bar_close_1600_v1'}


def first_exit(frame, *, seed, **kwargs):
    if seed != entry_state(EMAPullbackRTH()):
        return et(kwargs['entry_at']),'missing_exit_state'
    event=structural_exit(frame,**kwargs,max_hold_bars=75,time_cap_reason='time_cap_75bars',timeframe_minutes=15)
    if event and event[1]=='underlying_2r_target':
        return event[0],'underlying_2_06r_target'
    return event

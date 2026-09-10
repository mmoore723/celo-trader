"""Observe bearish ORB RSI/MACD's frozen midpoint stop and 1.5R target."""
from dataclasses import asdict
from datetime import date, time
from functools import lru_cache
import hashlib
import inspect

from research.engine.simulator import Simulator, SimulationConfig
from research.engine.strategies.orb_rsi_macd import ORBRsiMacdShort, ORBRsiMacdShortConfig, _ema, _rsi
from research.engine.strategies.vwap_pullback import _session
from strategy_health.impulse_exit import et, first_exit as structural_exit

STRATEGY_ID = 'V2_SPY_ORB_RSI_MACD_SHORT'
PROTOCOL = 'orb_rsi_macd_midpoint_1_5r_intraday_completed5m_v1'


@lru_cache(maxsize=1)
def engine_hash():
    source='\n'.join(inspect.getsource(x) for x in (
        ORBRsiMacdShort,ORBRsiMacdShortConfig,_ema,_rsi,_session,Simulator,SimulationConfig,
    ))
    return hashlib.sha256(source.encode()).hexdigest()


def config_proof(config):
    return {k:v.isoformat() if isinstance(v,(date,time)) else v for k,v in asdict(config).items()}


def entry_state(strategy):
    return {'engine_hash':engine_hash(),'config':config_proof(strategy.config),
            'session_policy':'intraday_completed5m_close_1600_v1'}


def first_exit(frame, *, seed, **kwargs):
    if seed != entry_state(ORBRsiMacdShort()):
        return et(kwargs['entry_at']),'missing_exit_state'
    if kwargs['direction'] != 'bearish':
        return et(kwargs['entry_at']),'invalid_levels'
    event=structural_exit(frame,**kwargs,max_hold_bars=75,time_cap_reason='time_cap_75bars')
    if event and event[1]=='underlying_2r_target':
        return event[0],'underlying_1_5r_target'
    return event

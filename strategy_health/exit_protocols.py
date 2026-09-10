"""Explicit registry of implemented observation protocols, never order routes."""
from strategy_health import impulse_exit, supertrend_exit, momentum_exit, gap_fill_exit, trend_exit, vwap_exit
from strategy_health import afternoon_exit, fvg_exit, midday_exit, orb_exit, turtle_exit, reversion_exit
from strategy_health import ema_exit, rsi_macd_exit, compression_exit, range_sweep_exit
from strategy_health.context_orb_exit import PREMIUM_PROTOCOLS
from strategy_health import context_vwap_exit
from strategy_health import squeeze_exit

PROTOCOLS = {
    squeeze_exit.STRATEGY_ID: squeeze_exit.PROTOCOL,
    **context_vwap_exit.PROTOCOLS,
    **PREMIUM_PROTOCOLS,
    impulse_exit.STRATEGY_ID: impulse_exit.PROTOCOL,
    supertrend_exit.STRATEGY_ID: supertrend_exit.PROTOCOL,
    momentum_exit.STRATEGY_ID: momentum_exit.PROTOCOL,
    gap_fill_exit.STRATEGY_ID: gap_fill_exit.PROTOCOL,
    trend_exit.STRATEGY_ID: trend_exit.PROTOCOL,
    vwap_exit.STRATEGY_ID: vwap_exit.PROTOCOL,
    afternoon_exit.STRATEGY_ID: afternoon_exit.PROTOCOL,
    fvg_exit.STRATEGY_ID: fvg_exit.PROTOCOL,
    midday_exit.STRATEGY_ID: midday_exit.PROTOCOL,
    orb_exit.STRATEGY_ID: orb_exit.PROTOCOL,
    turtle_exit.STRATEGY_ID: turtle_exit.PROTOCOL,
    reversion_exit.STRATEGY_ID: reversion_exit.PROTOCOL,
    ema_exit.STRATEGY_ID: ema_exit.PROTOCOL,
    rsi_macd_exit.STRATEGY_ID: rsi_macd_exit.PROTOCOL,
    compression_exit.STRATEGY_ID: compression_exit.PROTOCOL,
    range_sweep_exit.STRATEGY_ID: range_sweep_exit.PROTOCOL,
}
SHORT_TRAIL_PROTOCOLS = {
    module.PROTOCOL: (module.STRATEGY_ID, module.LOW_WATER_PROTOCOL)
    for module in (momentum_exit, gap_fill_exit)
}


def candidate_metadata(strategy_id, strategy):
    protocol = PROTOCOLS.get(strategy_id)
    if protocol is None:
        return {}
    result = {"authored_exit_protocol": protocol}
    if strategy_id == supertrend_exit.STRATEGY_ID:
        result["authored_exit_state"] = supertrend_exit.entry_state(strategy)
    if strategy_id == momentum_exit.STRATEGY_ID:
        result["authored_exit_state"] = momentum_exit.entry_state(strategy)
    if strategy_id == gap_fill_exit.STRATEGY_ID:
        result["authored_exit_state"] = gap_fill_exit.entry_state(strategy)
    if strategy_id == trend_exit.STRATEGY_ID:
        result["authored_exit_state"] = trend_exit.entry_state(strategy)
    if strategy_id == vwap_exit.STRATEGY_ID:
        result["authored_exit_state"] = vwap_exit.entry_state(strategy)
    if strategy_id == afternoon_exit.STRATEGY_ID:
        result["authored_exit_state"] = afternoon_exit.entry_state(strategy)
    if strategy_id == fvg_exit.STRATEGY_ID:
        result["authored_exit_state"] = fvg_exit.entry_state(strategy)
    if strategy_id == midday_exit.STRATEGY_ID:
        result["authored_exit_state"] = midday_exit.entry_state(strategy)
    if strategy_id == orb_exit.STRATEGY_ID:
        result["authored_exit_state"] = orb_exit.entry_state(strategy)
    if strategy_id == turtle_exit.STRATEGY_ID:
        result["authored_exit_state"] = turtle_exit.entry_state(strategy)
    if strategy_id == reversion_exit.STRATEGY_ID:
        result["authored_exit_state"] = reversion_exit.entry_state(strategy)
    if strategy_id == ema_exit.STRATEGY_ID:
        result["authored_exit_state"] = ema_exit.entry_state(strategy)
    if strategy_id == rsi_macd_exit.STRATEGY_ID:
        result["authored_exit_state"] = rsi_macd_exit.entry_state(strategy)
    if strategy_id == compression_exit.STRATEGY_ID:
        result["authored_exit_state"] = compression_exit.entry_state(strategy)
    if strategy_id == range_sweep_exit.STRATEGY_ID:
        result["authored_exit_state"] = range_sweep_exit.entry_state(strategy)
    return result


def first_exit(protocol, frame, *, entry_at, entry_quote_at, direction, meta, now):
    common = dict(entry_at=entry_at, entry_quote_at=entry_quote_at, direction=direction, now=now)
    if protocol in context_vwap_exit.PROTOCOLS.values():
        strategy_id=next(key for key,value in context_vwap_exit.PROTOCOLS.items() if value==protocol)
        return context_vwap_exit.first_exit(frame, **common, meta=meta, strategy_id=strategy_id)
    if protocol == impulse_exit.PROTOCOL:
        return impulse_exit.first_exit(frame, **common, stop=meta["underlying_stop"], target=meta["underlying_target"])
    if protocol == supertrend_exit.PROTOCOL:
        return supertrend_exit.first_exit(frame, **common, seed=meta.get("authored_exit_state"))
    if protocol == trend_exit.PROTOCOL:
        return trend_exit.first_exit(frame, **common, seed=meta.get("authored_exit_state"),
                                     stop=meta["underlying_stop"], target=meta["underlying_target"])
    if protocol == vwap_exit.PROTOCOL:
        return vwap_exit.first_exit(frame, **common, seed=meta.get("authored_exit_state"),
                                    stop=meta["underlying_stop"], target=meta["underlying_target"])
    if protocol == afternoon_exit.PROTOCOL:
        return afternoon_exit.first_exit(frame, **common, seed=meta.get("authored_exit_state"),
                                         stop=meta["underlying_stop"], target=meta["underlying_target"])
    if protocol == fvg_exit.PROTOCOL:
        return fvg_exit.first_exit(frame, **common, seed=meta.get("authored_exit_state"),
                                   stop=meta["underlying_stop"], target=meta["underlying_target"])
    if protocol == midday_exit.PROTOCOL:
        return midday_exit.first_exit(frame, **common, seed=meta.get("authored_exit_state"),
                                      stop=meta["underlying_stop"], target=meta["underlying_target"])
    if protocol == orb_exit.PROTOCOL:
        return orb_exit.first_exit(frame, **common, seed=meta.get("authored_exit_state"),
                                   stop=meta["underlying_stop"], target=meta["underlying_target"])
    if protocol == turtle_exit.PROTOCOL:
        return turtle_exit.first_exit(frame, **common, seed=meta.get("authored_exit_state"),
                                      stop=meta["underlying_stop"], target=meta["underlying_target"])
    if protocol == reversion_exit.PROTOCOL:
        return reversion_exit.first_exit(frame, **common, seed=meta.get("authored_exit_state"),
                                         stop=meta["underlying_stop"], target=meta["underlying_target"])
    if protocol == ema_exit.PROTOCOL:
        return ema_exit.first_exit(frame, **common, seed=meta.get("authored_exit_state"),
                                   stop=meta["underlying_stop"], target=meta["underlying_target"])
    if protocol == rsi_macd_exit.PROTOCOL:
        return rsi_macd_exit.first_exit(frame, **common, seed=meta.get("authored_exit_state"),
                                        stop=meta["underlying_stop"], target=meta["underlying_target"])
    if protocol == compression_exit.PROTOCOL:
        return compression_exit.first_exit(frame, **common, seed=meta.get("authored_exit_state"),
                                           stop=meta["underlying_stop"], target=meta["underlying_target"])
    if protocol == range_sweep_exit.PROTOCOL:
        return range_sweep_exit.first_exit(frame, **common, seed=meta.get("authored_exit_state"),
                                           stop=meta["underlying_stop"], target=meta["underlying_target"])
    if protocol in {momentum_exit.PROTOCOL, momentum_exit.LOW_WATER_PROTOCOL}:
        return momentum_exit.first_exit(frame, **common, seed=meta.get("authored_exit_state"),
                                        stop=meta["underlying_stop"], target=meta["underlying_target"],
                                        short_low_water=protocol == momentum_exit.LOW_WATER_PROTOCOL)
    if protocol in {gap_fill_exit.PROTOCOL, gap_fill_exit.LOW_WATER_PROTOCOL}:
        return gap_fill_exit.first_exit(frame, **common, seed=meta.get("authored_exit_state"),
                                       stop=meta["underlying_stop"], target=meta["underlying_target"],
                                       short_low_water=protocol == gap_fill_exit.LOW_WATER_PROTOCOL)
    raise ValueError("Unknown authored exit protocol")

"""Explicit registry of implemented observation protocols, never order routes."""
from strategy_health import impulse_exit, supertrend_exit, momentum_exit, gap_fill_exit, trend_exit, vwap_exit
from strategy_health import afternoon_exit, fvg_exit, midday_exit, orb_exit

PROTOCOLS = {
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
    return result


def first_exit(protocol, frame, *, entry_at, entry_quote_at, direction, meta, now):
    common = dict(entry_at=entry_at, entry_quote_at=entry_quote_at, direction=direction, now=now)
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
    if protocol in {momentum_exit.PROTOCOL, momentum_exit.LOW_WATER_PROTOCOL}:
        return momentum_exit.first_exit(frame, **common, seed=meta.get("authored_exit_state"),
                                        stop=meta["underlying_stop"], target=meta["underlying_target"],
                                        short_low_water=protocol == momentum_exit.LOW_WATER_PROTOCOL)
    if protocol in {gap_fill_exit.PROTOCOL, gap_fill_exit.LOW_WATER_PROTOCOL}:
        return gap_fill_exit.first_exit(frame, **common, seed=meta.get("authored_exit_state"),
                                       stop=meta["underlying_stop"], target=meta["underlying_target"],
                                       short_low_water=protocol == gap_fill_exit.LOW_WATER_PROTOCOL)
    raise ValueError("Unknown authored exit protocol")

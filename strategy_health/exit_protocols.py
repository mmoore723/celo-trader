"""Explicit registry of implemented observation protocols, never order routes."""
from strategy_health import impulse_exit, supertrend_exit

PROTOCOLS = {
    impulse_exit.STRATEGY_ID: impulse_exit.PROTOCOL,
    supertrend_exit.STRATEGY_ID: supertrend_exit.PROTOCOL,
}


def candidate_metadata(strategy_id, strategy):
    protocol = PROTOCOLS.get(strategy_id)
    if protocol is None:
        return {}
    result = {"authored_exit_protocol": protocol}
    if strategy_id == supertrend_exit.STRATEGY_ID:
        result["authored_exit_state"] = supertrend_exit.entry_state(strategy)
    return result


def first_exit(protocol, frame, *, entry_at, entry_quote_at, direction, meta, now):
    common = dict(entry_at=entry_at, entry_quote_at=entry_quote_at, direction=direction, now=now)
    if protocol == impulse_exit.PROTOCOL:
        return impulse_exit.first_exit(frame, **common, stop=meta["underlying_stop"], target=meta["underlying_target"])
    if protocol == supertrend_exit.PROTOCOL:
        return supertrend_exit.first_exit(frame, **common, seed=meta.get("authored_exit_state"))
    raise ValueError("Unknown authored exit protocol")

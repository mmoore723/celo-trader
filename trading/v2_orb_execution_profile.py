"""Locked execution profile shared by reviewed V2 TSLA paper strategies.

Paper trading is where this profile earns evidence today.  If the strategy is
ever separately approved for live trading, its *decision rules* must remain
the same.  The account and actual broker fill can differ; the signal,
contract-selection, entry-side, and exit policy cannot.
"""
from __future__ import annotations


V2_ORB_STRATEGY_ID = "V2_ORB_PULLBACK"
V2_TREND_STRATEGY_ID = "V2_TREND_CONT"
V2_SPY_TREND_STRATEGY_ID = "V2_SPY_TREND_CONT"
V2_PAPER_STRATEGY_IDS = frozenset({
    V2_ORB_STRATEGY_ID, V2_TREND_STRATEGY_ID, V2_SPY_TREND_STRATEGY_ID,
})


def uses_v2_orb_execution_profile(strategy_id: object) -> bool:
    """Return whether a trade/signal uses the locked V2 paid-data policy.

    This intentionally accepts no paper/live argument.  Mode controls broker
    routing, not the strategy being measured.
    """
    return str(strategy_id or "").strip().upper() in V2_PAPER_STRATEGY_IDS

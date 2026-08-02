"""
router_gates/confidence_floor.py — Gate 8: confidence floor filter.

Split out of the old single router_gates.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""

import logging

from config import get_settings
from router_gates.helpers import _journal_dropped

logger = logging.getLogger("celo_trader.router_gates")


def apply_confidence_floor(signals: list, ticker: str, min_confidence: float, quiet: bool = False) -> list:
    # quiet=True added 2026-07-24 alongside the signal_journal write below —
    # without it, backtester.py's 1-min-resolution replay of route_signals()
    # (see backtester.py) would flood signal_journal with thousands of fake
    # historical rows every backtest run. Default False preserves the exact
    # prior behavior for the one live call site in strategy_router.py.
    _before_list = list(signals)
    # Paper-only, separately measured research cohort. Main-tier behavior is
    # unchanged; this never runs when the account is configured for live mode.
    # Candidates stay tagged when execution is paused, preserving separate
    # scorecard evidence instead of blending them into the main tier.
    _opportunity_floor = min_confidence - 0.04
    _settings = get_settings()
    _paper_only = bool(_settings.get("paper_trading", True))
    _cohort_enabled = _paper_only and bool(_settings.get("opportunity_tier_enabled", False))
    for signal in signals:
        if _opportunity_floor <= signal.confidence < min_confidence:
            signal.tier = "opportunity"
    signals = [s for s in signals if s.confidence >= min_confidence or
               (_cohort_enabled and s.confidence >= _opportunity_floor)]
    if len(signals) < len(_before_list) and not quiet:
        _dropped = len(_before_list) - len(signals)
        _journal_dropped(_before_list, signals, ticker, "confidence_floor",
                          f"below {min_confidence:.0%} floor")
        logger.info(
            "router: dropped %d low-confidence signal(s) for %s (floor=%.0f%%)",
            _dropped, ticker, min_confidence * 100,
        )
    return signals

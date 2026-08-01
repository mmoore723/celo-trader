"""
router_gates/confidence_floor.py — Gate 8: confidence floor filter.

Split out of the old single router_gates.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""

import logging

from router_gates.helpers import _journal_dropped

logger = logging.getLogger("celo_trader.router_gates")


def apply_confidence_floor(signals: list, ticker: str, min_confidence: float, quiet: bool = False) -> list:
    # quiet=True added 2026-07-24 alongside the signal_journal write below —
    # without it, backtester.py's 1-min-resolution replay of route_signals()
    # (see backtester.py) would flood signal_journal with thousands of fake
    # historical rows every backtest run. Default False preserves the exact
    # prior behavior for the one live call site in strategy_router.py.
    _before_list = list(signals)
    signals = [s for s in signals if s.confidence >= min_confidence]
    if len(signals) < len(_before_list) and not quiet:
        _dropped = len(_before_list) - len(signals)
        _journal_dropped(_before_list, signals, ticker, "confidence_floor",
                          f"below {min_confidence:.0%} floor")
        logger.info(
            "router: dropped %d low-confidence signal(s) for %s (floor=%.0f%%)",
            _dropped, ticker, min_confidence * 100,
        )
    return signals

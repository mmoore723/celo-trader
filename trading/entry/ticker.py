"""
trading/entry/ticker.py — Phase-based ticker selection.

Split out of trading/entry.py (2026-08-01, file-size cleanup); no logic
changed, only relocated. NOTE: confirmed via grep before this split that
select_ticker() is not called anywhere in the live tick loop
(trading/entry/tick.py cycles the scan watchlist directly instead, a
changeover config.py has a stale comment about, line ~310). Kept, not
deleted, per this project's live-money-code convention of not deleting
unused code just because it's unused (see risk/manager.py's ORB_TIME_BOX
note for the same pattern).
"""

from __future__ import annotations

import logging
from typing import Optional

from broker import AlpacaClient, TradierClient
from config import get_settings
from signals import relative_volume_rank
from trading.state import _now_et

logger = logging.getLogger("celo_trader.trading_logic")


def select_ticker(alpaca: AlpacaClient, tradier: TradierClient, balance: float) -> Optional[str]:
    """
    Phase-based ticker selection:
    Phase 1 (<$25k): SPY and QQQ only — tightest spreads, most liquid options
    Phase 2 ($25k+): Expands to top large-cap movers ranked by relative volume
    Also checks trading window before selecting any ticker.
    """
    from config import get_trading_windows as _gtw

    _now_et_time = _now_et()
    _hm          = _now_et_time.hour * 60 + _now_et_time.minute
    _windows = _gtw(balance)
    _in_window = any(
        int(s.split(":")[0]) * 60 + int(s.split(":")[1]) <= _hm <=
        int(e.split(":")[0]) * 60 + int(e.split(":")[1])
        for s, e in _windows
    )
    if not _in_window:
        logger.debug("Trading blocked: Outside trading window")
        return None

    phase2_boundary = float(get_settings().get("phase_2_boundary", 25000.0))

    if balance < phase2_boundary:
        candidates = ["SPY", "QQQ"]
        bar_dict = {}
        for t in candidates:
            bars, err = alpaca.get_bars(t, "5Min", limit=25)
            if not err and bars:
                bar_dict[t] = bars
        ranked = relative_volume_rank(bar_dict) if bar_dict else candidates
        selected = ranked[0] if ranked else candidates[0]
        logger.info("Phase 1 ticker (SPY/QQQ): %s", selected)
        return selected

    else:
        anchor_tickers  = ["SPY", "QQQ"]
        expanded_pool   = ["NVDA", "META", "MSFT", "GOOGL", "AAPL", "AMZN", "TSLA"]
        bar_dict = {}
        for t in anchor_tickers + expanded_pool:
            bars, err = alpaca.get_bars(t, "5Min", limit=25)
            if not err and bars:
                bar_dict[t] = bars

        ranked = relative_volume_rank(bar_dict)
        extra    = [t for t in ranked if t in expanded_pool][:2]
        universe = list(dict.fromkeys(anchor_tickers + extra))
        logger.info("Phase 2 universe: %s", universe)
        return universe[0] if universe else "SPY"


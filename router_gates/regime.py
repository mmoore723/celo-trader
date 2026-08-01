"""
router_gates/regime.py — Gate 1: regime gate (OFF by default — see
regime_manager.py).

Split out of the old single router_gates.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""

import logging

import pandas as pd

from database import log_event as _db_log
import regime_manager as _regime_mgr
from regime_manager import compute_regime, regime_allows
from router_gates.helpers import _journal_dropped

logger = logging.getLogger("celo_trader.router_gates")


def apply_regime_gate(signals: list, df: pd.DataFrame, ticker: str, quiet: bool = False) -> list:
    if not (_regime_mgr.REGIME_GATE_ENABLED and signals):
        return signals
    _regime = compute_regime(df)
    if _regime == "neutral":
        return signals
    _before_list = list(signals)
    signals = [s for s in signals if regime_allows(s.strategy_id, s.direction, _regime)]
    if len(signals) != len(_before_list) and not quiet:
        _journal_dropped(_before_list, signals, ticker, "regime_gate", f"regime={_regime}")
        try:
            _db_log("INFO", "bar_eval",
                    f"⚪ [{ticker}] Regime={_regime} filtered "
                    f"{len(_before_list) - len(signals)} counter-regime signal(s).")
        except Exception:
            pass
    return signals

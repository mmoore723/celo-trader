"""
router_gates/vetoes.py — Gate 9 (conflict veto) and Gate 10 (volume ROC
veto). Both are "check_*" functions instead of filters — they return a
bool because a True result means route_signals() must return []
IMMEDIATELY, skipping every gate after it and the final audit-log call.
This early-return behavior is preserved exactly as it was before this
extraction — do not change these two to plain filters without also
updating strategy_router.route_signals()'s early-return checks.

Split out of the old single router_gates.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""

import logging

import pandas as pd

from database import log_event as _db_log
from config import get_settings as _get_settings
from trading.annotations import emit_annotation as _emit_ann
from router_gates.helpers import _journal_dropped

logger = logging.getLogger("celo_trader.router_gates")


# ── 9. Conflict veto (early return if True) ───────────────────────────────────
# If the top two signals disagree on direction and their confidence gap is
# within veto_band, the market is sending mixed signals — skip both.

def check_conflict_veto(signals: list, today: pd.DataFrame, ticker: str, veto_band: float, quiet: bool = False) -> bool:
    if len(signals) < 2:
        return False
    _top, _second = signals[0], signals[1]
    if not (_top.direction != _second.direction and
            (_top.confidence - _second.confidence) <= veto_band):
        return False

    if quiet:
        return True

    _detail = f"{_top.strategy_id} {_top.direction} vs {_second.strategy_id} {_second.direction} within {veto_band:.0%}"
    _journal_dropped([_top, _second], [], ticker, "conflict_veto", _detail)

    _db_log(
        "INFO", "scan",
        f"{ticker} — Conflict veto: {_top.strategy_id} {_top.direction} "
        f"({_top.confidence:.0%}) vs {_second.strategy_id} {_second.direction} "
        f"({_second.confidence:.0%}) within {veto_band:.0%} band — "
        f"market is ambiguous, skipping both.",
    )
    logger.info(
        "router: conflict veto fired for %s (%s vs %s)",
        ticker, _top.strategy_id, _second.strategy_id,
    )
    try:
        _cv_ts = str(today.iloc[-1]["time"])
        _cv_px = float(today.iloc[-1]["close"])
        _emit_ann(ticker, "marker", "veto",
                  label=f"✗ Conflict {_top.strategy_id}↑↓{_second.strategy_id}",
                  ts=_cv_ts, price=_cv_px, color="#64748b")
    except Exception:
        pass
    return True


# ── 10. Volume ROC gate (early return if True) ────────────────────────────────
# Prevent entries when buying pressure is already fading. Compares avg volume
# of the last 3 bars vs the prior 3 bars.

def check_volume_roc_veto(signals: list, today: pd.DataFrame, ticker: str, quiet: bool = False) -> bool:
    if not (signals and len(today) >= 6):
        return False

    _recent_vol = today["volume"].iloc[-3:].mean()
    _prior_vol  = today["volume"].iloc[-6:-3].mean()
    _vol_roc    = _recent_vol / _prior_vol if _prior_vol > 0 else 1.0

    _roc_threshold = float(_get_settings().get("vol_roc_threshold", 0.50))
    if _vol_roc >= _roc_threshold:
        return False

    if quiet:
        return True

    _journal_dropped(signals, [], ticker, "volume_roc_veto",
                      f"ROC {_vol_roc:.2f} < {_roc_threshold:.2f}")

    _db_log(
        "INFO", "scan",
        f"{ticker} — Volume ROC veto: recent vol {_recent_vol:.0f} "
        f"vs prior {_prior_vol:.0f} (ROC={_vol_roc:.2f} < {_roc_threshold:.2f}) "
        f"— fading momentum, staying in cash.",
    )
    logger.info(
        "router: vol_roc_veto %s — vol declining %.0f%% (%.0f → %.0f)",
        ticker, (1 - _vol_roc) * 100, _prior_vol, _recent_vol,
    )
    try:
        _veto_ts = str(today.iloc[-1]["time"])
        _veto_px = float(today.iloc[-1]["close"])
        _emit_ann(ticker, "marker", "veto",
                  label=f"✗ Vol ROC {_vol_roc:.2f}",
                  ts=_veto_ts, price=_veto_px, color="#64748b")
    except Exception:
        pass
    return True

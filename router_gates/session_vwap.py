"""
router_gates/session_vwap.py — Gate 2 (session bias penalty) and Gate 3
(intraday VWAP weight).

Split out of the old single router_gates.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""

import logging

import pandas as pd

from database import log_event as _db_log

logger = logging.getLogger("celo_trader.router_gates")


# ── 2. Session bias penalty ───────────────────────────────────────────────────
# Compare current price to the session open price only. VWAP is intentionally
# excluded — individual strategies already gate on it. Penalty scales with
# RVOL so high-volume days allow more counter-session latitude.

def apply_session_bias_penalty(signals: list, today: pd.DataFrame, ticker: str, quiet: bool = False) -> list:
    if not (signals and len(today) >= 2):
        return signals

    _first_bar    = today.iloc[0]
    _last_bar     = today.iloc[-1]
    _session_open = float(_first_bar.get("open", _first_bar["close"]))
    _curr_close   = float(_last_bar["close"])

    _session_bearish = _curr_close < _session_open
    _session_bullish = _curr_close > _session_open
    if not (_session_bearish or _session_bullish):
        return signals

    _bias_label = "bearish" if _session_bearish else "bullish"
    _penalized  = 0

    _last_rvol = float(_last_bar.get("rvol", 1.0) or 1.0)
    if _last_rvol > 1.5:
        _dynamic_penalty = 0.02   # high volume — V-reversals are real
    elif _last_rvol < 1.0:
        _dynamic_penalty = 0.10   # low volume — counter-trend = chop
    else:
        _dynamic_penalty = 0.05   # normal days

    for _sig in signals:
        _counter = (
            (_session_bearish and _sig.direction == "bullish") or
            (_session_bullish and _sig.direction == "bearish")
        )
        if _counter:
            _old_conf       = _sig.confidence
            _sig.confidence = max(0.0, _sig.confidence - _dynamic_penalty)
            _penalized      += 1
            logger.debug(
                "router: session_bias=%s penalized %s %s conf %.2f→%.2f (rvol=%.2f penalty=%.0f%%)",
                _bias_label, _sig.strategy_id, _sig.direction,
                _old_conf, _sig.confidence, _last_rvol, _dynamic_penalty * 100,
            )
    if _penalized and not quiet:
        _db_log(
            "INFO", "scan",
            f"{ticker} — Session bias={_bias_label}: "
            f"{_penalized} counter-session signal(s) penalized -{_dynamic_penalty:.0%} "
            f"(RVOL={_last_rvol:.1f}× | close={_curr_close:.2f} vs session_open={_session_open:.2f})",
        )
    signals.sort(key=lambda s: s.confidence, reverse=True)
    return signals


# ── 3. Intraday VWAP trend — weighted 20% factor ─────────────────────────────
# VWAP slope is ONE input, not a binary gate. It contributes 20% weight to
# signal confidence; the strategy's own technical edge provides 80%.

def apply_vwap_weight(signals: list, today: pd.DataFrame, ticker: str) -> list:
    if not (signals and len(today) >= 12):
        return signals

    _vwap_now   = float(today.iloc[-1].get("vwap", 0) or 0)
    _vwap_10    = float(today.iloc[-10].get("vwap", _vwap_now) or _vwap_now)
    _vwap_slope = (_vwap_now - _vwap_10) / max(_vwap_10, 1.0)

    _VWAP_SLOPE_THRESH = 0.0005   # 0.05% over 10 bars = clear institutional flow
    _VWAP_WEIGHT       = 0.20     # VWAP trend accounts for 20% of signal weight

    _slope_adjusted = 0
    for _sig in signals:
        _against_flow = (
            (_vwap_slope < -_VWAP_SLOPE_THRESH and _sig.direction == "bullish") or
            (_vwap_slope >  _VWAP_SLOPE_THRESH and _sig.direction == "bearish")
        )
        if _against_flow:
            _old_conf = _sig.confidence
            _sig.confidence = round(max(0.0, _sig.confidence * (1.0 - _VWAP_WEIGHT)), 4)
            _slope_adjusted += 1
            logger.debug(
                "router: vwap_weighted ×0.80: %s %s conf %.3f→%.3f (slope=%.3f%% flow=%s)",
                _sig.strategy_id, _sig.direction, _old_conf, _sig.confidence,
                _vwap_slope * 100, "bearish" if _vwap_slope < 0 else "bullish",
            )

    if _slope_adjusted:
        _flow_dir = "bearish" if _vwap_slope < 0 else "bullish"
        logger.debug(
            "router: vwap_weighted 20%% factor applied to %d counter-flow signal(s) "
            "— intraday flow=%s (slope=%.3f%%)",
            _slope_adjusted, _flow_dir, _vwap_slope * 100,
        )
        signals.sort(key=lambda s: s.confidence, reverse=True)
    return signals

"""
router_gates/move_consensus.py — Gate 6 (large-session-move gate) and
Gate 7 (directional consensus filter/penalty).

Split out of the old single router_gates.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""

import logging

import pandas as pd

from database import log_event as _db_log
from strategies.base import MarketStructureAnalyzer
from router_gates.helpers import _journal_dropped

logger = logging.getLogger("celo_trader.router_gates")


# ── 6. Large-session-move gate (gap / momentum-day filter) ───────────────────
# If the session has already moved ±1.5%+ from the opening bar, it is a gap
# or momentum day. Counter-trend entries before 13:00 ET are high-risk.

def apply_large_move_gate(signals: list, today: pd.DataFrame, ticker: str) -> list:
    if not (signals and len(today) >= 2):
        return signals

    _so     = float(today.iloc[0].get("open", today.iloc[0]["close"]))
    _sc     = float(today.iloc[-1]["close"])
    _sm_pct = (_sc - _so) / max(_so, 1.0)
    _btime  = today.iloc[-1]["time"]
    _bmin   = (_btime.hour * 60 + _btime.minute) if hasattr(_btime, "hour") else 600

    _LARGE_MOVE = 0.015   # 1.5% from open = gap/momentum day
    if abs(_sm_pct) > _LARGE_MOVE and _bmin < 13 * 60:
        _trend_dir = "bullish" if _sm_pct > 0 else "bearish"
        _capped    = 0
        for _sig in signals:
            if _sig.direction != _trend_dir:
                _sig.confidence = min(_sig.confidence, 0.70)   # below 0.74 floor
                _capped += 1
        if _capped:
            logger.info(
                "router: large_session_move=%.1f%% before 13:00 — "
                "%d counter-trend signal(s) capped (trend=%s)",
                _sm_pct * 100, _capped, _trend_dir,
            )
            signals.sort(key=lambda s: s.confidence, reverse=True)
    return signals


# ── 7. Directional consensus filter ───────────────────────────────────────────
# Three independent indicators (price vs VWAP, VWAP slope, market structure)
# must ALL agree before a direction is considered "established" enough to
# hard-block the opposite side. 2/3 agreement gets a soft penalty instead.

def apply_directional_consensus(signals: list, today: pd.DataFrame, ticker: str, quiet: bool = False) -> list:
    if not (signals and len(today) >= 20):
        return signals

    _dc_last   = today.iloc[-1]
    _dc_rvol   = float(_dc_last.get("rvol", 1.0) or 1.0)
    _dc_close  = float(_dc_last["close"])
    _dc_vwap   = float(_dc_last.get("vwap", _dc_close) or _dc_close)

    _dc_price_bull = _dc_close > _dc_vwap
    _dc_price_bear = _dc_close < _dc_vwap

    _dc_vwap_20    = float(today.iloc[-20].get("vwap", _dc_vwap) or _dc_vwap)
    _dc_slope_pct  = (_dc_vwap - _dc_vwap_20) / max(_dc_vwap_20, 1.0)
    _dc_slope_bull = _dc_slope_pct > 0.0005    # +0.05% over 100 min
    _dc_slope_bear = _dc_slope_pct < -0.0005

    _dc_msa    = MarketStructureAnalyzer(today)
    _dc_trend  = _dc_msa.classify_trend()
    _dc_struct_bull = _dc_trend == "uptrend"
    _dc_struct_bear = _dc_trend == "downtrend"

    _bull_score = sum([_dc_price_bull, _dc_slope_bull, _dc_struct_bull])
    _bear_score = sum([_dc_price_bear, _dc_slope_bear, _dc_struct_bear])

    _dc_before_list = list(signals)
    _dc_before = len(signals)
    if _bull_score == 3:
        signals = [s for s in signals if s.direction == "bullish"]
        if _dc_before > len(signals) and not quiet:
            _journal_dropped(_dc_before_list, signals, ticker, "directional_consensus",
                              f"3/3 bullish (slope+{_dc_slope_pct*100:.2f}% {_dc_trend} RVOL {_dc_rvol:.1f}x)")
            logger.info(
                "router: dir_consensus=BULLISH 3/3 (slope+%.3f%% %s RVOL=%.1f×) — %d PUT(s) blocked",
                _dc_slope_pct * 100, _dc_trend, _dc_rvol, _dc_before - len(signals),
            )
            _db_log("INFO", "scan",
                f"{ticker} — Directional consensus BULLISH 3/3 "
                f"(price>VWAP slope+{_dc_slope_pct*100:.2f}% {_dc_trend} RVOL {_dc_rvol:.1f}×) "
                f"— PUT entries blocked.")
    elif _bear_score == 3:
        signals = [s for s in signals if s.direction == "bearish"]
        if _dc_before > len(signals) and not quiet:
            _journal_dropped(_dc_before_list, signals, ticker, "directional_consensus",
                              f"3/3 bearish (slope{_dc_slope_pct*100:.2f}% {_dc_trend} RVOL {_dc_rvol:.1f}x)")
            logger.info(
                "router: dir_consensus=BEARISH 3/3 (slope%.3f%% %s RVOL=%.1f×) — %d CALL(s) blocked",
                _dc_slope_pct * 100, _dc_trend, _dc_rvol, _dc_before - len(signals),
            )
            _db_log("INFO", "scan",
                f"{ticker} — Directional consensus BEARISH 3/3 "
                f"(price<VWAP slope{_dc_slope_pct*100:.2f}% {_dc_trend} RVOL {_dc_rvol:.1f}×) "
                f"— CALL entries blocked.")
    else:
        # Soft penalty only: 2/3 lean → reduce counter-direction by 20%
        if _bull_score == 2:
            for _s in signals:
                if _s.direction == "bearish":
                    _s.confidence = round(max(0.0, _s.confidence * 0.80), 4)
        elif _bear_score == 2:
            for _s in signals:
                if _s.direction == "bullish":
                    _s.confidence = round(max(0.0, _s.confidence * 0.80), 4)

    if len(signals) != _dc_before:
        signals.sort(key=lambda s: s.confidence, reverse=True)
    return signals

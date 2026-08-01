"""
trading/position_manager/constants.py — Exit-engine tuning constants.

Split out of trading/position_manager.py (2026-08-01, file-size cleanup);
no values changed, only relocated. Several external modules import these
directly (backtest_exit_sim.py, backtest_trail_multiplier.py,
backtest_stage1_signals.py) — see package __init__.py for the re-exports
that keep those imports working unchanged.
"""

from __future__ import annotations

# ── ATR / swing trailing stop constants ────────────────────────────────────
_ATR_TRAIL_MULTIPLIER = 2.0   # UNUSED — dynamically overridden below; kept for fidelity, see note in risk/manager.py about not deleting unused live-money constants
_DELTA_APPROX         = 0.40  # approximate option delta for underlying->option conversion
_SWING_LOOKBACK       = 20    # bars to look back for swing high/low

# ── VWAP breach + trend breakdown constants ────────────────────────────────
_ADX_WEAK_THRESHOLD   = 20    # ADX < 20 -> trend has no directional strength
_VWAP_BREACH_BARS     = 5     # 1-min VWAP breach bars (fallback if 5-min unavailable)
_VWAP_5M_BREACH_BARS  = 2     # 5-min VWAP breach bars (cleaner structural signal)

# ── Time cap of last resort (safety net only) ──────────────────────────────
_TIME_CAP_WINNER_MIN  = 90    # UNUSED — real cap is risk.RiskManager.ORB_TIME_BOX_WINNER
_TIME_CAP_LOSER_MIN   = 20    # UNUSED — real cap is config.EARLY_TIMEBOX_MIN

# ── ATR trail warmup ────────────────────────────────────────────────────────
_MIN_TRAIL_WARMUP_MIN = 5     # don't arm trail until 5 min into trade

# ── Multi-timeframe exit tuning ─────────────────────────────────────────────
_TRAIL_MULT_1H_WITH    = 2.5  # 1-hour trend aligned with trade -> give runners room
_TRAIL_MULT_BASE       = 2.0  # default when 1-hour is neutral
_TRAIL_MULT_1H_AGAINST = 1.5  # 1-hour trend opposing trade -> tighter stop
_TRAIL_MULT_TIGHT      = 1.0  # RSI exhaustion OR near 15-min swing level -> very tight

_RSI_EXHAUST_CALL      = 72   # 5-min RSI above this while long = momentum exhaustion
_RSI_EXHAUST_PUT       = 28   # 5-min RSI below this while short = momentum exhaustion
_MACD_FADE_BARS        = 2    # MACD histogram declining for N consecutive 5-min bars
_15M_SWING_PROX_PCT    = 0.003  # within 0.3% of 15-min swing level = near resistance/support

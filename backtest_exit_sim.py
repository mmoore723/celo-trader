"""
backtest_exit_sim.py — Real exit-engine bridge for the backtester.

Calls risk.py's real RiskManager.evaluate_exit_conditions() — the same
function live trading uses (structural stop -> ATR/swing trail -> VWAP+
trend-dead -> stage1/stage2 -> momentum-death -> time caps) — instead of
backtester.py's old hand-copied approximation. The ATR-trail multiplier
itself (widens with 1h trend support, tightens on 5m RSI exhaustion/MACD
fade/15m swing proximity) is real too — see backtest_trail_multiplier.py,
split out to keep both files under 200 lines. Fails open to the flat base
multiplier if the extra 1h/15m fetch is missing, same as live's own fallback.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from trading.position_manager import (
    _structural_swing_stop,
    _underlying_stop_to_option,
    _DELTA_APPROX,
    _MIN_TRAIL_WARMUP_MIN,
    _SWING_LOOKBACK,
    _VWAP_5M_BREACH_BARS,
)
from trading.mtf_features import compute_adx, ema_stack_aligned
from backtest_trail_multiplier import dynamic_trail_multiplier
from backtest_stage1_signals import compute_stage1_signals
from risk import RiskManager
from config import _DEFAULTS

# Live gates the ATR trail on +15% option gain (position_manager.py line ~509,
# `_trail_profit_gate = _opt_gain_pct >= 0.15`) — not a named constant there,
# so pinned here with the same value + a pointer back to the source line.
_TRAIL_PROFIT_GATE = 0.15

# Initial ATR stop multiplier, before the trail arms (position_manager.py
# `_init_mult = 2.5`, same non-named-constant situation as above).
_INITIAL_ATR_MULT = 2.5


class ExitSimState:
    """
    Per-open-trade state carried bar-to-bar, mirroring position_manager.py's
    per-position `ps` dict (peak underlying, ratcheting trail, VWAP breach
    counter, structural stop set once at entry).
    """

    __slots__ = (
        "direction", "entry_price", "entry_bar_time",
        "struct_stop_price", "initial_atr_stop", "atr_trail_stop",
        "peak_underlying", "vwap_breached_bars",
    )

    def __init__(
        self,
        direction: str,
        entry_price: float,
        entry_bar_time,
        struct_stop_price: Optional[float],
        atr_at_entry: Optional[float],
    ):
        self.direction         = direction
        self.entry_price       = entry_price
        self.entry_bar_time    = entry_bar_time
        self.struct_stop_price = struct_stop_price
        self.atr_trail_stop    = None
        self.peak_underlying   = None
        self.vwap_breached_bars = 0

        # Initial ATR-based stop (replaces the old flat 20% fallback), set
        # once at entry exactly like position_manager.py's first-tick logic.
        self.initial_atr_stop = None
        if atr_at_entry:
            _atr_opt_stop = entry_price - _INITIAL_ATR_MULT * atr_at_entry * _DELTA_APPROX
            self.initial_atr_stop = max(
                entry_price * 0.70, min(entry_price * 0.85, _atr_opt_stop)
            )


_risk = RiskManager()
# BUG FIX 2026-07-21: risk.py's class default (ORB_STAGE1_GAIN=0.25) is
# stale/overridden in live trading — trading/entry.py always sets the
# per-request instance value from the user's settings
# (orb_stage1_gain_pct, default 50 in config.py's _DEFAULTS), so live
# actually runs at +50%, not +25%. This backtest module never applied
# that override, so every run today was silently testing a 25% profit-
# lock, not the 50% live actually uses. Backtests have no per-user
# settings context, so the canonical default from config.py is the
# correct fidelity choice here.
_risk.ORB_STAGE1_GAIN = float(_DEFAULTS.get("orb_stage1_gain_pct", 50)) / 100.0
# BUG FIX 2026-07-22 (full-audit finding 1.2): the line above only synced
# ORB_STAGE1_GAIN. evaluate_exit_conditions() (risk.py) also reads
# ORB_STOP_PCT and 5 more stage1-tuning knobs directly, and live syncs ALL
# 7 every tick (see trading/entry.py's "Sync user-editable trade parameters"
# block). This module is specifically the one that claims fidelity with
# live's real exit engine, so it's the highest-priority place to get this
# right — left unsynced, these 6 were silently at risk.py's raw class
# defaults, correct today only by coincidence.
_risk.ORB_STOP_PCT                 = float(_DEFAULTS.get("orb_stop_loss_pct", 20)) / 100.0
_risk.STAGE1_DYNAMIC_ENABLED        = bool(_DEFAULTS.get("stage1_dynamic_enabled", True))
_risk.STAGE1_ATR_TARGET_MULT        = float(_DEFAULTS.get("stage1_atr_target_mult", 2.0))
_risk.STAGE1_FLOOR_FRACTION_OF_TARGET = float(_DEFAULTS.get("stage1_floor_fraction_of_target", 45)) / 100.0
_risk.STAGE1_RVOL_FADE_THRESHOLD    = float(_DEFAULTS.get("stage1_rvol_fade_threshold", 1.0))
_risk.STAGE1_MOMENTUM_REQUIRE_BOTH  = bool(_DEFAULTS.get("stage1_momentum_require_both", True))


def _update_trail_and_vwap(
    state: ExitSimState, day_df: pd.DataFrame, idx: int, current_opt_price: float,
    df_1h: Optional[pd.DataFrame] = None, df_15m: Optional[pd.DataFrame] = None,
) -> tuple[Optional[float], bool, Optional[float], bool]:
    """
    Ratchets the ATR/swing trail and updates the VWAP-breach counter for one
    bar. Returns (vwap_value, trend_dead, atr_target_price, momentum_fading)
    for this bar. Mutates `state`.

    atr_target_price/momentum_fading (added 2026-07-21) feed the dynamic
    stage1 trigger in risk.py — same signals/formula as live's
    position_manager.py, recomputed fresh each bar (not frozen at entry) so
    the target adapts as volatility/momentum change through the trade.
    """
    bar = day_df.iloc[idx]
    underlying_now = float(bar["close"])

    if state.direction == "bullish":
        state.peak_underlying = max(state.peak_underlying or underlying_now, underlying_now)
    else:
        state.peak_underlying = min(state.peak_underlying or underlying_now, underlying_now)

    atr = float(bar["atr"]) if "atr" in day_df.columns and pd.notna(bar.get("atr")) else None
    elapsed_min = (bar["time"] - state.entry_bar_time).total_seconds() / 60

    # BUG FIX 2026-07-21: this was hardcoded to 0.0 and never actually used,
    # so the trail armed after 5 minutes elapsed REGARDLESS of profit — live
    # requires +15% option gain too (position_manager.py's `_trail_profit_
    # gate`). Without this, the trail was firing almost immediately on nearly
    # every trade (5-min bars mean elapsed_min>=5 after just ONE bar), which
    # is exactly why atr_trail_stop dominated the exit-reason mix in both
    # audit runs today. Confirmed via the exit-mix data, not assumed.
    opt_gain_pct = (
        (current_opt_price - state.entry_price) / state.entry_price
        if state.entry_price else 0.0
    )

    if (atr is not None
            and elapsed_min >= _MIN_TRAIL_WARMUP_MIN
            and opt_gain_pct >= _TRAIL_PROFIT_GATE
            and state.peak_underlying is not None):
        # Point-in-time slices — only bars closed at or before the current
        # bar are visible, same no-lookahead rule as the rest of this file.
        _bar_time  = bar["time"]
        _1h_slice  = (df_1h[df_1h["time"] <= _bar_time]  if df_1h  is not None and not df_1h.empty  else None)
        _15m_slice = (df_15m[df_15m["time"] <= _bar_time] if df_15m is not None and not df_15m.empty else None)
        trail_mult = dynamic_trail_multiplier(
            state.direction, _1h_slice, day_df.iloc[: idx + 1], _15m_slice,
        )
        if state.direction == "bullish":
            atr_stop_u = state.peak_underlying - trail_mult * atr
        else:
            atr_stop_u = state.peak_underlying + trail_mult * atr
        atr_stop_opt = _underlying_stop_to_option(state.entry_price, underlying_now, atr_stop_u)

        swing_u = _structural_swing_stop(day_df.iloc[: idx + 1], state.direction, lookback=_SWING_LOOKBACK)
        if swing_u is not None:
            swing_opt = _underlying_stop_to_option(state.entry_price, underlying_now, swing_u)
            new_trail = max(atr_stop_opt, swing_opt)
        else:
            new_trail = atr_stop_opt

        # Ratchet: trail can only tighten, never loosen (matches live).
        if state.atr_trail_stop is None or new_trail > state.atr_trail_stop:
            state.atr_trail_stop = new_trail

    vwap = float(bar["vwap"]) if "vwap" in day_df.columns and pd.notna(bar.get("vwap")) else None
    if vwap is not None:
        breached_now = (
            (state.direction == "bullish" and underlying_now < vwap) or
            (state.direction == "bearish" and underlying_now > vwap)
        )
        state.vwap_breached_bars = state.vwap_breached_bars + 1 if breached_now else 0

    trend_dead = False
    if state.vwap_breached_bars >= _VWAP_5M_BREACH_BARS:
        bar_slice = day_df.iloc[: idx + 1]
        adx = compute_adx(bar_slice)
        ema_ok = ema_stack_aligned(bar_slice, state.direction)
        trend_dead = (adx is not None and adx < 20) and not ema_ok

    # Dynamic stage1 trigger inputs (2026-07-21) — split out to
    # backtest_stage1_signals.py to keep this file under 200 lines.
    atr_target_price, momentum_fading = compute_stage1_signals(
        state.direction, state.entry_price, atr,
        _risk.STAGE1_ATR_TARGET_MULT, day_df.iloc[: idx + 1],
        require_both=_risk.STAGE1_MOMENTUM_REQUIRE_BOTH,
    )

    return vwap, trend_dead, atr_target_price, momentum_fading


def evaluate_bt_exit(
    state: ExitSimState,
    day_df: pd.DataFrame,
    idx: int,
    current_opt_price: float,
    opt_bar_best: float,
    opt_bar_worst: float,
    stage1_done: bool,
    stage1_be_price: Optional[float],
    peak_opt_price: float,
    rvol: float,
    df_1h: Optional[pd.DataFrame] = None,
    df_15m: Optional[pd.DataFrame] = None,
) -> tuple[bool, str]:
    """
    One bar of the real risk.py exit hierarchy. Checks the conservative
    (worst-case) price first — this is what actually threatens a stop —
    then the best-case price for profit-taking conditions, same "stops
    before targets" convention the backtester already used pre-fix.

    While stage1_done, only the worst-case price is checked: stage2's
    floor and the winner time-cap are the only live conditions, and both
    are either adverse-price or elapsed-time based, not profit-target based.
    """
    bar = day_df.iloc[idx]
    vwap, trend_dead, atr_target_price, momentum_fading = _update_trail_and_vwap(
        state, day_df, idx, current_opt_price, df_1h=df_1h, df_15m=df_15m,
    )
    trail_armed = state.atr_trail_stop is not None
    effective_atr_stop = state.atr_trail_stop or state.initial_atr_stop

    def _check(current_price: float) -> tuple[bool, str]:
        return _risk.should_exit(
            state.entry_price, current_price,
            entry_time        = state.entry_bar_time,
            now                = bar["time"],
            stage1_done        = stage1_done,
            stage1_be_price    = stage1_be_price,
            peak_price         = peak_opt_price,
            struct_stop_price  = state.struct_stop_price,
            atr_trail_stop     = effective_atr_stop,
            trail_armed        = trail_armed,
            vwap               = vwap,
            vwap_breached      = state.vwap_breached_bars >= 1,
            trend_dead         = trend_dead,
            direction          = state.direction,
            rvol               = rvol,
            atr_target_price   = atr_target_price,   # dynamic stage1 trigger (2026-07-21)
            momentum_fading    = momentum_fading,
        )

    should_exit, reason = _check(opt_bar_worst)
    if should_exit or stage1_done:
        return should_exit, reason

    return _check(opt_bar_best)

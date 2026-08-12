"""
backtest_exit_sim_simplified.py — 3-rule exit engine, A/B'd against the
current 9+-condition stack in backtest_exit_sim.py.

WHY THIS EXISTS (2026-07-22): published overfitting research names 8-10
tunable variables as the danger zone for a trading strategy, recommending
2-4 key inputs instead — and today's own STRUCT_STOP_MODE A/B test showed
exactly that fragility symptom (4 variants, 4 different outcomes, all
negative, just from changing one input). The current exit engine
(risk.py's evaluate_exit_conditions(), see backtest_exit_sim.py) has NINE+
separately-named exit paths: structural_stop, initial_atr_stop/atr_trail_
stop, vwap_trend_dead, vwap_breach_profitable, peak_giveback, stage1_atr_
target/stage1_momentum_fade/stage1_volume_fade/stage1_static_fallback,
stage2_trail_stop, early_momentum_stop_20pct, momentum_dead_exit, and two
time caps.

This file strips that down to exactly 3 rules, per user + second-opinion
sign-off on 2026-07-22:
  1. HARD STOP  — struct_stop_price (structural, when the strategy supplied
     one) else initial_atr_stop (both already computed in ExitSimState,
     unchanged from the existing engine — no new catastrophe-stop logic
     needed, just using what's already there as a single concept).
  2. CHANDELIER EXIT — ONE ATR trailing stop at the published 3.0x
     multiplier (Charles Le Beau's original Chandelier Exit spec), replacing
     the entire stage1/stage2/momentum-fade/vwap-dead/peak-giveback cluster.
     No partial scale-out — this is a full-position exit, unlike the
     current stack's 50%-then-trail structure. That trade-off is
     intentional per the "strip to the core three" instruction, not an
     oversight — flagged clearly to the user in the handoff.
  3. TIME CAP — ONE unified cap (not separate winner/loser), purely to kill
     theta bleed on a stalled, sideways trade. SIMPLIFIED_TIME_CAP_MIN is a
     testable/tunable single number, not two.

CAVEAT: this is a hypothesis test, not a replacement decision. Compare via
ab_test_exit_complexity.py before this touches live or becomes any kind of
default.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from backtest_exit_sim import ExitSimState
from trading.position_manager import _underlying_stop_to_option

# Charles Le Beau's original Chandelier Exit spec: 22-period ATR, 3.0x
# multiplier. This codebase already computes a comparable ATR series
# elsewhere (14-period, not 22) — reusing that rather than adding a second
# ATR calculation is a deliberate "stay simple" choice; the 3.0x multiplier
# is the part actually under test here, not the lookback period.
CHANDELIER_ATR_MULT = 3.0

# One unified time cap, replacing the current stack's separate 60m-loser /
# 90m-winner split. Midpoint pick, pending its own A/B if this branch wins.
SIMPLIFIED_TIME_CAP_MIN = 75


def evaluate_bt_exit_simplified(
    state: ExitSimState,
    day_df: pd.DataFrame,
    idx: int,
    current_opt_price: float,
) -> tuple[bool, str]:
    """
    One bar of the simplified 3-rule exit hierarchy. Checks the bar's worst
    price first (adverse-move rules), same "stops before targets" convention
    as the full engine, though rule 2 here is itself just a trailing stop
    (no separate profit-target check to order against).
    """
    bar = day_df.iloc[idx]
    underlying_now = float(bar["close"])
    entry_time = state.entry_bar_time
    now = bar["time"]
    elapsed_min = (now - entry_time).total_seconds() / 60

    if state.direction == "bullish":
        state.peak_underlying = max(state.peak_underlying or float(bar["high"]), float(bar["high"]))
    else:
        state.peak_underlying = min(state.peak_underlying or float(bar["low"]), float(bar["low"]))

    # ── Rule 1: hard stop (catastrophe) ───────────────────────────────────
    hard_stop = state.struct_stop_price if state.struct_stop_price is not None else state.initial_atr_stop
    if hard_stop is not None and current_opt_price <= hard_stop:
        return True, f"simplified_hard_stop (sl={hard_stop:.4f} current={current_opt_price:.4f})"

    # ── Rule 2: Chandelier exit — single 3.0x ATR trailing stop ───────────
    atr = float(bar["atr"]) if "atr" in day_df.columns and pd.notna(bar.get("atr")) else None
    if atr is not None and state.peak_underlying is not None:
        if state.direction == "bullish":
            trail_u = state.peak_underlying - CHANDELIER_ATR_MULT * atr
        else:
            trail_u = state.peak_underlying + CHANDELIER_ATR_MULT * atr
        prior_u = state.simplified_trail_underlying
        if (prior_u is None
                or (state.direction == "bullish" and trail_u > prior_u)
                or (state.direction == "bearish" and trail_u < prior_u)):
            state.simplified_trail_underlying = trail_u
            prior_u = trail_u
        # Keep the option-converted level for comparable backtest reporting,
        # but use the underlying crossing for the actual Chandelier decision.
        state.atr_trail_stop = _underlying_stop_to_option(state.entry_price, underlying_now, prior_u)
        crossed = underlying_now <= prior_u if state.direction == "bullish" else underlying_now >= prior_u
        if crossed:
            return True, (
                f"simplified_chandelier_3atr "
                f"(underlying={underlying_now:.4f} trail={prior_u:.4f})"
            )

    # ── Rule 3: one unified time cap ──────────────────────────────────────
    if elapsed_min >= SIMPLIFIED_TIME_CAP_MIN:
        return True, f"simplified_time_cap_{SIMPLIFIED_TIME_CAP_MIN}m (held={elapsed_min:.1f}min)"

    return False, "hold"

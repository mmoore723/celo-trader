"""
trading/simplified_exit_live.py — live counterpart to
backtest_exit_sim_simplified.py's 3-rule exit engine.

WHY THIS EXISTS (2026-07-22): today's ab_test_exit_complexity.py showed the
current 9+-condition exit stack (risk.py's evaluate_exit_conditions())
strangles winners relative to a stripped-down 3-rule alternative — same
average loss, 4.3x bigger average wins, realized R:R up from 0.20x-0.27x to
1.17x-1.29x, stacked with the prior_swing structural-stop fix. Wired into
live per explicit instruction, gated by SIMPLIFIED_EXIT_MODE in config.py's
_DEFAULTS (default True) so it can be flipped off in one settings change if
live behavior looks wrong — same reversibility every other fix this session
shipped with, not a one-way door.

Reuses per-position state trading/position_manager.py already tracks
unconditionally for every open position (ps["peak_underlying"],
ps["struct_stop_price"], ps["initial_atr_stop"]) — no new state, no new
per-tick bar fetches. Only the DECISION logic differs from the complex path.

Rules (identical spec to the backtest version — see that file's docstring
for the full reasoning):
  1. HARD STOP    — struct_stop_price if the strategy supplied one, else
                     initial_atr_stop.
  2. CHANDELIER   — single 3.0x ATR trailing stop off the underlying's
                     peak (Charles Le Beau's original spec). The underlying,
                     not an option quote, decides whether that level broke.
                     Full-position exit,
                     no partial scale-out — that's the deliberate trade-off
                     vs. the stage1/stage2 structure, not an oversight.
  3. TIME CAP     — one unified cap, not a separate winner/loser split.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

# Same constants as the backtest engine — keep these two files in sync if
# either changes; they're deliberately duplicated (not imported across
# live/backtest) to avoid coupling live's runtime to a backtest-only module.
CHANDELIER_ATR_MULT     = 3.0
SIMPLIFIED_TIME_CAP_MIN = 75


def evaluate_simplified_live_exit(
    ps: dict,
    entry_price: float,
    current_price: float,
    entry_time: Optional[datetime],
    now: datetime,
    direction: str,
    atr: Optional[float],
    underlying_now: float,
) -> tuple[bool, str]:
    """
    One tick of the simplified 3-rule exit hierarchy for a live position.
    `ps` is the same per-position state dict _manage_open_position() already
    maintains — this function reads from it and writes the trail back into
    it (ps["simplified_trail_stop"], kept separate from ps["atr_trail_stop"]
    so flipping the mode off mid-session can't hand the complex path a
    trail value it didn't compute itself).
    """
    from trading.position_manager import _underlying_stop_to_option

    elapsed_min = (now - entry_time).total_seconds() / 60 if entry_time else 0.0

    # ── Rule 1: hard stop (catastrophe) ───────────────────────────────────
    hard_stop = ps.get("struct_stop_price") or ps.get("initial_atr_stop")
    if hard_stop is not None and current_price <= hard_stop:
        return True, f"simplified_hard_stop (sl={hard_stop:.4f} current={current_price:.4f})"

    # ── Rule 2: Chandelier exit — single 3.0x ATR trailing stop ───────────
    # A Chandelier is an UNDERLYING-price exit.  Using current option premium
    # to test this level mixed two different instruments: IV, theta, gamma and
    # the bid/ask can move an option through a converted level even while the
    # underlying has not invalidated the trend.  Keep the converted option
    # value only for dashboard display; test the actual underlying crossing.
    peak_u = ps.get("peak_underlying")
    if atr is not None and peak_u is not None:
        peak_u = float(peak_u)
        if direction == "bullish":
            trail_u = peak_u - CHANDELIER_ATR_MULT * atr
        else:
            trail_u = peak_u + CHANDELIER_ATR_MULT * atr
        prev_trail_u = ps.get("simplified_trail_underlying")
        if (prev_trail_u is None
                or (direction == "bullish" and trail_u > prev_trail_u)
                or (direction == "bearish" and trail_u < prev_trail_u)):
            ps["simplified_trail_underlying"] = trail_u
            prev_trail_u = trail_u
        ps["simplified_trail_stop"] = _underlying_stop_to_option(
            entry_price, underlying_now, float(prev_trail_u))
        crossed = (
            underlying_now <= prev_trail_u if direction == "bullish"
            else underlying_now >= prev_trail_u
        )
        if crossed:
            return True, (
                f"simplified_chandelier_3atr "
                f"(underlying={underlying_now:.4f} trail={prev_trail_u:.4f})"
            )

    # ── Rule 3: one unified time cap ──────────────────────────────────────
    if elapsed_min >= SIMPLIFIED_TIME_CAP_MIN:
        return True, f"simplified_time_cap_{SIMPLIFIED_TIME_CAP_MIN}m (held={elapsed_min:.1f}min)"

    return False, "hold"

"""
signals/orb_breakout.py — Legacy raw ORB breakout detector, plus the
ORB_SIGNAL_MIN / ORB_RVOL_THRESHOLD constants used across the signals
package and by strategies/base.py.

Split out of the old single signals.py (2026-08-01, file-size cleanup); no
logic changed, only relocated.

Kept as one function (detect_orb_breakout) — it's already a single,
self-contained detection routine (find OR → walk bars → two gates → return
on first qualifying bar), not the heavy multi-phase mutable-state loop
class that warranted the "irreducible function" exception elsewhere in
this refactor (e.g. trading/entry/tick.py's _tick).
"""

import logging
from typing import Optional

import pandas as pd

from signals.ranges import get_opening_range
from signals.vwap import compute_vwap
from signals.rvol import compute_rvol

logger = logging.getLogger("celo_trader.signals")

# Earliest bar that can trigger an ORB breakout signal.
# The 15-minute opening range spans 09:30, 09:35, and 09:40.
# The range is complete only after the 09:40 bar closes, so the FIRST
# valid breakout bar is 09:45 (minutes-since-midnight = 585).
ORB_SIGNAL_MIN: int = 9 * 60 + 45   # 585 — signals blocked before this

try:
    from config import VOLUME_FILTER_MULTIPLIER as _CFG_RVOL
    ORB_RVOL_THRESHOLD: float = float(_CFG_RVOL)   # reads config.py (default 1.2)
except Exception:
    ORB_RVOL_THRESHOLD: float = 1.2                 # fallback if config unavailable


def detect_orb_breakout(df: pd.DataFrame) -> Optional[tuple[str, float]]:
    """
    Legacy raw-breakout ORB signal. NOT called by the live pipeline —
    the live ORB strategy is the retest state machine in
    strategies/inst_orb.py, wired in via strategy_router.ACTIVE_STRATEGIES.
    Kept here for reference/backtesting only; do not assume "called once
    per tick" (stale claim from before the retest-entry rework).

    Returns (direction, rvol) or None.
      direction : "bullish" | "bearish"
      rvol      : Entry_Volume_Multiplier of the breakout candle (used in audit log)

    Logic:
    1. Find the Opening Range (09:30 bar).
    2. Walk subsequent bars looking for a candle that closes outside OR High/Low.
    3. Gate 1 — RVOL: breakout candle volume ≥ 200% of 10-day same-slot average.
    4. Gate 2 — VWAP: bullish requires close > VWAP; bearish requires close < VWAP.
    5. Signal fires on the FIRST qualifying breakout bar of the session.

    df must contain today's 5-min bars sorted ascending.
    If df spans multiple sessions the function operates on the most recent day.

    FIX 2026-07-28: rvol_today used to reindex against today_df.index AFTER
    it was reset to 0..N-1 — the same misalignment bug already fixed in
    strategy_router.py::_build_indicator_frame() and
    trading/diagnostics.py::_log_bar_thinking(). Captures the pre-reset
    index first, same pattern as those two fixes, so this function is
    correct if it's ever wired back into the live pipeline.
    """
    if df.empty or len(df) < 2:
        return None

    # Isolate today's bars — capture the PRE-reset index for the rvol
    # reindex below before resetting today_df's own index to 0..N-1.
    latest_date = df["time"].dt.date.max()
    today_idx   = df.index[df["time"].dt.date == latest_date]
    today_df    = df[df["time"].dt.date == latest_date].reset_index(drop=True)

    if len(today_df) < 2:
        return None

    or_info = get_opening_range(today_df)
    if or_info is None:
        return None

    or_high = or_info["high"]
    or_low  = or_info["low"]

    # Compute VWAP and RVOL (pass full df so prior days inform RVOL calc)
    vwap_series = compute_vwap(today_df)
    rvol_series = compute_rvol(df, lookback_days=10)
    # Positional assign via .to_numpy(): today_idx (pre-reset) and today_df
    # are in the same row order, so this sidesteps index alignment entirely
    # — same fix pattern as strategy_router.py/trading/diagnostics.py.
    rvol_today  = pd.Series(
        rvol_series.reindex(today_idx).to_numpy(), index=today_df.index
    )

    for idx in range(1, len(today_df)):
        bar     = today_df.iloc[idx]
        bar_min = bar["time"].hour * 60 + bar["time"].minute

        # ── 15-min range guard: do not fire before 09:45 ─────────────────────
        # The OR spans 09:30, 09:35, and 09:40. Signals from any bar inside
        # that window would be measuring a breakout against an incomplete range.
        if bar_min < ORB_SIGNAL_MIN:
            continue

        close = float(bar["close"])
        vwap  = float(vwap_series.iloc[idx]) if not pd.isna(vwap_series.iloc[idx]) else None
        rvol  = float(rvol_today.iloc[idx])  if not pd.isna(rvol_today.iloc[idx])  else 0.0

        # ── Breakout direction ────────────────────────────────────────────────
        if close > or_high:
            direction = "bullish"
        elif close < or_low:
            direction = "bearish"
        else:
            continue

        # ── Gate 1: Volume ≥ 200% of 10-day average ──────────────────────────
        if rvol < ORB_RVOL_THRESHOLD:
            logger.debug(
                "ORB %s rejected — RVOL %.2f < %.1f at %s",
                direction, rvol, ORB_RVOL_THRESHOLD, bar["time"],
            )
            continue   # next bar may re-confirm with volume

        # ── Gate 2: VWAP direction alignment ─────────────────────────────────
        if vwap is not None:
            if direction == "bullish" and close <= vwap:
                logger.debug(
                    "ORB bullish rejected — close %.4f ≤ VWAP %.4f at %s",
                    close, vwap, bar["time"],
                )
                continue
            if direction == "bearish" and close >= vwap:
                logger.debug(
                    "ORB bearish rejected — close %.4f ≥ VWAP %.4f at %s",
                    close, vwap, bar["time"],
                )
                continue

        logger.info(
            "ORB signal: %s | OR=[%.4f, %.4f] close=%.4f RVOL=%.2fx VWAP=%s bar=%s",
            direction, or_low, or_high, close, rvol,
            f"{vwap:.4f}" if vwap else "n/a", bar["time"],
        )
        return direction, rvol   # (direction, Entry_Volume_Multiplier)

    return None

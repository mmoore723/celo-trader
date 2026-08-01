"""
strategies/base.py — shared primitives for all strategy evaluators.

Contents
────────
  Signal                     — dataclass returned by every evaluator
  MarketStructureAnalyzer    — 5-bar swing detection + trend classification
  _get_dynamic_rvol_threshold — context-aware RVOL gate
  _rvol_threshold_reason     — audit-log companion (plain-English reason)
  _has_recent_fvg            — Fair Value Gap scanner helper
  _find_swings               — 2-bar pivot helper (dashboard chart overlays only)
  _signal_cooldown           — module-level dict: tracks last fire time per strategy+ticker
  SIGNAL_COOLDOWN_MINUTES    — minimum gap between same-strategy signals on same ticker
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date as _date

import numpy as np
import pandas as pd

from signals import ORB_RVOL_THRESHOLD

logger = logging.getLogger("celo_trader.strategies.base")

# ── Cooldown tracker ──────────────────────────────────────────────────────────
# Keys: (strategy_id, ticker, date_str)  →  last-fired pd.Timestamp
# Date component ensures the cooldown resets automatically at midnight without
# any explicit flush — the bot runs 24/7 via systemd, so without a date key
# a signal fired at 14:30 on Monday would still block 09:45 on Tuesday.
_signal_cooldown: dict[tuple[str, str, str], pd.Timestamp] = {}
SIGNAL_COOLDOWN_MINUTES: int = 20


# ── Signal container ──────────────────────────────────────────────────────────

@dataclass(order=True)
class Signal:
    """Ranked by confidence descending (highest first in a sorted list)."""
    confidence:  float
    strategy_id: str          = field(compare=False)
    direction:   str          = field(compare=False)
    rvol:        float        = field(compare=False)
    trigger_bar: pd.Timestamp = field(compare=False)
    meta:        dict         = field(compare=False, default_factory=dict)


# ── MarketStructureAnalyzer ───────────────────────────────────────────────────

class MarketStructureAnalyzer:
    """
    Identifies swing highs (SH) and swing lows (SL) using a 5-bar rolling
    lookback and classifies the current trend from the last two swing pairs.

    Usage:
        msa = MarketStructureAnalyzer(today_df)
        trend = msa.classify_trend()          # "uptrend" | "downtrend" | "consolidation"
        msa.confirmed_higher_low()            # True if last SL > prev SL
        msa.confirmed_lower_high()            # True if last SH < prev SH
        msa.last_swing_high() / .prev_swing_high()
        msa.last_swing_low()  / .prev_swing_low()
    """

    LOOKBACK: int = 5

    def __init__(self, df: pd.DataFrame) -> None:
        self._df     = df.reset_index(drop=True)
        self._swings: list[dict] | None = None

    # ── Swing detection ───────────────────────────────────────────────────────

    def _detect_swings(self) -> list[dict]:
        # FIX 2026-07-31 (backtest performance): this used to call df.iloc[i]
        # / df.iloc[slice] inside a per-bar Python loop — each pandas .iloc[]
        # access has real overhead (dtype resolution, Series construction)
        # that a raw numpy array doesn't. Confirmed via py-spy profiling a
        # real stuck backtest: this one function was 90% of ALL CPU time,
        # dominated by pandas internals (_slice/fast_xs/__getitem__), not
        # the actual min/max arithmetic. Every strategy using
        # MarketStructureAnalyzer rebuilds it fresh per bar (by design, for
        # correct backtester replay), so this function still runs
        # O(bars-in-day) times per day — extracting to numpy once here
        # doesn't change that call count, but makes each call's O(n) scan
        # dramatically cheaper (compiled numpy slicing/min/max instead of
        # per-element pandas access). Same pivot logic, same output as the
        # original .iloc-based version — only the access method changed.
        pivots: list[dict] = []
        df = self._df
        n  = len(df)
        lb = self.LOOKBACK

        highs   = df["high"].to_numpy()
        lows    = df["low"].to_numpy()
        volumes = df["volume"].to_numpy() if "volume" in df.columns else None
        atrs    = df["atr"].to_numpy()    if "atr"    in df.columns else None
        _time_col = df["time"]   # kept as a pandas Series (not numpy) so
                                  # swing["time"] stays a real Timestamp,
                                  # same type callers already expect —
                                  # .iat[] is pandas' fast scalar accessor,
                                  # far cheaper than the old whole-row .iloc[i].

        # ── Confirmed pivots: require lb bars on BOTH sides ───────────────────
        # These are fully confirmed — higher accuracy, 5-bar lag vs. live price.
        for i in range(lb, n - lb):
            bar_high = highs[i]
            bar_low  = lows[i]
            left_high_max  = highs[i - lb : i].max()
            right_high_max = highs[i + 1 : i + lb + 1].max()
            left_low_min   = lows[i - lb : i].min()
            right_low_min  = lows[i + 1 : i + lb + 1].min()

            if bar_high > left_high_max and bar_high > right_high_max:
                pivots.append({"idx": i, "price": float(bar_high),
                               "type": "high", "time": _time_col.iat[i]})
            if bar_low < left_low_min and bar_low < right_low_min:
                pivots.append({"idx": i, "price": float(bar_low),
                               "type": "low",  "time": _time_col.iat[i]})

        # ── Real-time fallback: left-side only for the last lb bars ───────────
        # The confirmed loop above can never detect pivots within the last lb bars
        # because right-side bars don't exist yet. This creates a 5-minute lag on
        # 1-min charts — the bot enters trend-continuation setups at the end of the
        # move rather than the start.
        #
        # Volume-confirmation gate: a real-time pivot must have volume >= the
        # rolling 20-bar mean of the left window. This filters single-wick retail
        # noise on volatile names (NFLX, TSLA) that would otherwise flip trend
        # classification 3–4 times in a single 15-minute window.
        # ATR-body gate: the pivot extension must exceed 15% of the bar's ATR so
        # micro-wicks (≤1 tick past the prior extreme) are ignored.
        VOL_LOOKBACK = 20
        rt_start = max(lb, n - lb)
        for i in range(rt_start, n):
            bar_high = highs[i]
            bar_low  = lows[i]
            _left_start = max(0, i - lb)
            left_high = highs[_left_start : i]
            left_low  = lows[_left_start : i]
            if left_high.size == 0:
                continue

            # Volume gate — bar must show at least average participation
            if volumes is not None:
                vol_window = volumes[max(0, i - VOL_LOOKBACK) : i]
                vol_mean   = float(vol_window.mean()) if vol_window.size else 0.0
                _bv = volumes[i]
                bar_vol = float(_bv) if (_bv is not None and not (isinstance(_bv, float) and np.isnan(_bv))) else 0.0
                if vol_mean > 0 and bar_vol < vol_mean:
                    continue   # below-average volume → retail noise, skip

            # ATR body gate — extension past the prior extreme must be meaningful
            bar_atr = None
            if atrs is not None:
                _a = atrs[i]
                if _a is not None and not (isinstance(_a, float) and np.isnan(_a)):
                    bar_atr = float(_a)

            left_high_max = left_high.max()
            left_low_min  = left_low.min()

            if bar_high > left_high_max:
                extension = float(bar_high) - float(left_high_max)
                if bar_atr and bar_atr > 0 and extension < 0.15 * bar_atr:
                    pass   # micro-wick — skip this pivot
                else:
                    pivots.append({"idx": i, "price": float(bar_high),
                                   "type": "high", "time": _time_col.iat[i], "realtime": True})

            if bar_low < left_low_min:
                extension = float(left_low_min) - float(bar_low)
                if bar_atr and bar_atr > 0 and extension < 0.15 * bar_atr:
                    pass   # micro-wick — skip this pivot
                else:
                    pivots.append({"idx": i, "price": float(bar_low),
                                   "type": "low",  "time": _time_col.iat[i], "realtime": True})

        pivots.sort(key=lambda p: p["idx"])
        return pivots

    @property
    def swings(self) -> list[dict]:
        if self._swings is None:
            self._swings = self._detect_swings()
        return self._swings

    def _highs(self) -> list[dict]:
        return [s for s in self.swings if s["type"] == "high"]

    def _lows(self) -> list[dict]:
        return [s for s in self.swings if s["type"] == "low"]

    def last_swing_high(self) -> float | None:
        h = self._highs()
        return h[-1]["price"] if h else None

    def prev_swing_high(self) -> float | None:
        h = self._highs()
        return h[-2]["price"] if len(h) >= 2 else None

    def last_swing_low(self) -> float | None:
        lo = self._lows()
        return lo[-1]["price"] if lo else None

    def prev_swing_low(self) -> float | None:
        lo = self._lows()
        return lo[-2]["price"] if len(lo) >= 2 else None

    def classify_trend(self) -> str:
        """
        Classify market trend using two passes:

        Pass 1 — structural (confirmed swings, 5-bar lag):
          HH + HL  → uptrend
          LH + LL  → downtrend

        Pass 2 — real-time override (no lag):
          If confirmed pairs aren't available OR their conclusion is
          "consolidation", compare the current bar's close against the
          most recently detected swing levels:
            close > last swing high → uptrend
            close < last swing low  → downtrend
          This eliminates the 25-minute blind spot where a market structure
          shift has clearly happened (price already past the prior swing) but
          the swing-pair logic hasn't caught up yet.
        """
        highs = self._highs()
        lows  = self._lows()

        # Pass 1: structural trend from confirmed swing pairs
        structural = "consolidation"
        if len(highs) >= 2 and len(lows) >= 2:
            hh = highs[-1]["price"] > highs[-2]["price"]
            hl = lows[-1]["price"]  > lows[-2]["price"]
            lh = highs[-1]["price"] < highs[-2]["price"]
            ll = lows[-1]["price"]  < lows[-2]["price"]
            if hh and hl:
                structural = "uptrend"
            elif lh and ll:
                structural = "downtrend"

        if structural != "consolidation":
            return structural

        # Pass 2: real-time override — current close vs. swing levels
        # Only fires when structural pass returned "consolidation" (no clear
        # HH/HL or LH/LL pair yet) so it never overrides a confirmed trend.
        if not self._df.empty:
            current_close = float(self._df.iloc[-1]["close"])
            last_sh = self.last_swing_high()
            last_sl = self.last_swing_low()
            if last_sh is not None and current_close > last_sh:
                return "uptrend"
            if last_sl is not None and current_close < last_sl:
                return "downtrend"

        return "consolidation"

    def confirmed_higher_low(self) -> bool:
        lows = self._lows()
        return len(lows) >= 2 and lows[-1]["price"] > lows[-2]["price"]

    def confirmed_lower_high(self) -> bool:
        highs = self._highs()
        return len(highs) >= 2 and highs[-1]["price"] < highs[-2]["price"]


# ── Dynamic RVOL threshold ────────────────────────────────────────────────────

def _get_dynamic_rvol_threshold(
    bar_min: int,
    close: float,
    or_low: "float | None",
    vwap: "float | None",
    strategy_id: str = "",
    msa_confirmed: bool = False,
) -> float:
    if msa_confirmed:
        # MSA confirmation means structure is validated — return the relaxed
        # threshold directly and bypass the early-session floor entirely.
        # Previously the floor of 1.0 silently overrode this 0.75, blocking
        # valid early-session entries even when structure was fully confirmed.
        return 0.75
    elif strategy_id == "CHAN_BREAK":
        threshold = 1.0
    else:
        mid_day = (10 * 60 + 30) <= bar_min <= (13 * 60)
        if (mid_day
                and or_low is not None and close < or_low
                and vwap   is not None and close < vwap):
            threshold = 0.75
        else:
            threshold = ORB_RVOL_THRESHOLD

    # FIX 2026-07-28: mid_day's window starts at bar_min == 630 (10:30)
    # inclusive ("<="), but this floor used to check "> 630" (exclusive) —
    # at exactly 10:30 the mid-day relaxed threshold (0.75) would compute
    # correctly above, then get silently overridden back to 1.0 here since
    # the floor's strict comparison didn't consider 10:30 itself "past" the
    # boundary. Now uses ">=" to match mid_day's own boundary.
    floor = 0.75 if bar_min >= (10 * 60 + 30) else 1.0
    return max(threshold, floor)


def _rvol_threshold_reason(
    bar_min: int,
    close: float,
    or_low: "float | None",
    vwap: "float | None",
    strategy_id: str = "",
    msa_confirmed: bool = False,
) -> str:
    if msa_confirmed:
        return "structure confirmed (MSA) — relaxed to 0.75× (afternoon thinning expected)"
    if strategy_id == "CHAN_BREAK":
        return "CHAN_BREAK — 1.0× (channel touch needs real participation)"
    mid_day = (10 * 60 + 30) <= bar_min <= (13 * 60)
    if (mid_day and or_low is not None and close < or_low
            and vwap is not None and close < vwap):
        return "mid-day bleed (below OR Low + VWAP) — relaxed to 0.75×"
    return "default session threshold (ORB_RVOL_THRESHOLD)"


# ── FVG detection helper ──────────────────────────────────────────────────────

def _has_recent_fvg(today: pd.DataFrame, direction: str, lookback: int = 20) -> bool:
    """
    Return True if a confirmed Fair Value Gap of the given direction exists
    within the last `lookback` bars. Used by BOS_MSS to require imbalance
    evidence before firing a market-structure-shift signal.
    """
    n = len(today)
    if n < 3:
        return False
    window = min(lookback, n - 2)
    for k in range(n - 2, max(n - 2 - window, 1), -1):
        if k - 1 < 0:
            break
        b_prev = today.iloc[k - 1]
        b_next = today.iloc[k + 1]
        if direction == "bullish":
            if float(b_prev["low"]) > float(b_next["high"]):
                return True
        else:
            if float(b_prev["high"]) < float(b_next["low"]):
                return True
    return False


# ── 2-bar swing helper (dashboard chart overlays only) ────────────────────────

def _find_swings(df: pd.DataFrame, pivot_bars: int = 2) -> list[tuple[int, float, str]]:
    """
    2-bar lookback pivot detection — used ONLY by dashboard.py chart overlays
    for HH/LH/HL/LL visual labels. Trading decisions use MarketStructureAnalyzer
    (5-bar) instead. Keep these in sync if the cosmetic display ever changes.
    """
    pivots = []
    n = len(df)
    for i in range(pivot_bars, n - pivot_bars):
        hi = df.iloc[i]["high"]
        lo = df.iloc[i]["low"]
        left_bars  = df.iloc[i - pivot_bars : i]
        right_bars = df.iloc[i + 1 : i + pivot_bars + 1]
        if hi > left_bars["high"].max() and hi > right_bars["high"].max():
            pivots.append((i, float(hi), "high"))
        if lo < left_bars["low"].min() and lo < right_bars["low"].min():
            pivots.append((i, float(lo), "low"))
    return pivots


# ── Cooldown helpers ──────────────────────────────────────────────────────────

def _cooldown_key(strategy_id: str, ticker: str, bar_time: pd.Timestamp) -> tuple:
    """Key is (strategy, ticker, date) so cooldown auto-resets each trading day."""
    date_str = bar_time.strftime("%Y-%m-%d") if hasattr(bar_time, "strftime") else str(bar_time)[:10]
    return (strategy_id, ticker, date_str)


def check_cooldown(strategy_id: str, ticker: str, bar_time: pd.Timestamp) -> bool:
    """
    Return True if the strategy is BLOCKED by cooldown (fired too recently).
    Call before heavy gate evaluation to short-circuit fast.
    """
    key = _cooldown_key(strategy_id, ticker, bar_time)
    last = _signal_cooldown.get(key)
    if last is None:
        return False
    minutes_since = (bar_time - last).total_seconds() / 60
    return minutes_since < SIGNAL_COOLDOWN_MINUTES


def register_cooldown(strategy_id: str, ticker: str, bar_time: pd.Timestamp) -> None:
    """Record that this strategy just fired. Call immediately before returning a Signal."""
    key = _cooldown_key(strategy_id, ticker, bar_time)
    _signal_cooldown[key] = bar_time

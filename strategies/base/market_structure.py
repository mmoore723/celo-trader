"""
strategies/base/market_structure.py — MarketStructureAnalyzer: 5-bar swing
detection + trend classification.

Split out of the old single strategies/base.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.

Kept as a single class (not split further) — its methods share `self._df`
and the lazily-cached `self._swings` property across calls, and the class
is already a cohesive, single-responsibility unit.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


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
        #
        # FIX 2026-08-01 (late-entry diagnosis): requiring FULL average volume
        # on the pivot bar itself defeats the point of "real-time" detection —
        # volume typically CONFIRMS a move after it's underway, not at the
        # exact instant it turns, so a genuine reversal starting on merely
        # below-average volume was falling through to the 5-bar-lagged
        # confirmed path instead of registering immediately. Every audit this
        # session showed entries that die fast (LIQ_SWEEP losses averaging
        # 4-5 min held) — consistent with entering after the move already
        # happened, not at the inflection. Loosened to 50% of average instead
        # of 100% — still filters true single-wick noise, no longer defers
        # every merely-quiet-volume pivot to the laggy path.
        VOL_LOOKBACK = 20
        _RT_VOL_FLOOR_PCT = 0.50   # was 1.0 (full average) — see fix note above
        rt_start = max(lb, n - lb)
        for i in range(rt_start, n):
            bar_high = highs[i]
            bar_low  = lows[i]
            _left_start = max(0, i - lb)
            left_high = highs[_left_start : i]
            left_low  = lows[_left_start : i]
            if left_high.size == 0:
                continue

            # Volume gate — bar must show at least 50% of average participation
            if volumes is not None:
                vol_window = volumes[max(0, i - VOL_LOOKBACK) : i]
                vol_mean   = float(vol_window.mean()) if vol_window.size else 0.0
                _bv = volumes[i]
                bar_vol = float(_bv) if (_bv is not None and not (isinstance(_bv, float) and np.isnan(_bv))) else 0.0
                if vol_mean > 0 and bar_vol < vol_mean * _RT_VOL_FLOOR_PCT:
                    continue   # well below average volume → retail noise, skip

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

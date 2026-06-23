"""
strategy_router.py — Dynamic Multi-Strategy Signal Router

Evaluates strategy modules concurrently on every tick and returns the
highest-confidence qualifying Signal.  Every signal is tagged with a
Strategy_ID that propagates through the audit log.

Strategy IDs
────────────
  INST_ORB    — Institutional ORB (09:45–10:30). OR = 15-min range (9:30–9:44).
                Price > OR High + VWAP + volume > SMA20 × 2.0. MSA structure gate.
  BOS_MSS    — Break of Structure / Market Structure Shift (09:45+). LL→BOS bullish
                or HH→BOS bearish. Requires FVG confirmation + RVOL ≥ 1.5 + EMA50 alignment.
  VWAP_PB    — VWAP Pullback (09:45–EOD). Trend-continuation retest of VWAP.
  FVG        — Fair Value Gap (09:45+). 3-candle imbalance retest. ≥ 0.5× ATR gap.
  MID_BRK    — Mid-Day Breakdown (10:30–13:00). Price < OR Low + VWAP +
                MSA confirmed LH rejection. SHORT/PUT bias.
  AFT_REV    — Afternoon Reversal (13:00–15:30). Downtrend → confirmed HL,
                price breaks prior SH resistance + volume > SMA20 × 1.2.
  TREND_CONT — Trend Continuation (09:45–14:30). LH re-entry (bearish) or HL
                re-entry (bullish). RVOL ≥ 1.2. Pivot must be within 20 bars.
  CHAN_BREAK  — Channel Trendline Rejection (09:45–14:00). Descending/ascending
                channel touch + close-below/above-projection rejection candle.

All signals must pass through the existing RiskManager gates before entry:
  • 1% risk rule (balance-aware via get_risk_tier)
  • 1.6 R:R minimum (evaluate_rr)
  • 30% option premium hard stop
  • 45-minute theta exit timer

MarketStructureAnalyzer (MSA)
──────────────────────────────
  Reads price structure like a human trader:
    detect_swings()         → 5-bar rolling lookback for SH / SL pivots
    classify_trend()        → HH+HL=Uptrend | LH+LL=Downtrend | else Consolidation
    confirmed_higher_low()  → last SL > prev SL
    confirmed_lower_high()  → last SH < prev SH
  Session-specific evaluators instantiate MSA on the today-frame so
  structural context filters every entry gate — not just raw price levels.

Return value
────────────
  route_signals(df, ticker) → list[Signal]

  Signal is a dataclass:
    strategy_id : str          — one of the IDs above
    direction   : str          — "bullish" | "bearish"
    confidence  : float        — 0.0–1.0 composite score
    rvol        : float        — breakout candle RVOL
    trigger_bar : pd.Timestamp — bar timestamp where the signal fired
    meta        : dict         — strategy-specific details for the audit log

trading_logic._tick() calls route_signals() and uses the top-confidence
qualifying signal.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from signals import (
    compute_vwap,
    compute_vwap_bands,
    compute_rvol,
    get_opening_range,
    ORB_RVOL_THRESHOLD,
)
from risk import check_kill_lock
from database import log_event as _db_log

logger = logging.getLogger("celo_trader.strategy_router")

# ── Audit state — tracks last-logged structure so we don't spam the DB ────────
# Only logs a new structural event when the trend/swing state actually changes.
_last_audit_state: dict = {}   # keys: "trend", "last_sh", "last_sl", "ticker"

# ── Signal container ──────────────────────────────────────────────────────────

@dataclass(order=True)
class Signal:
    """Ranked by confidence descending (highest first in a sorted list)."""
    confidence:   float        # primary sort key
    strategy_id:  str   = field(compare=False)
    direction:    str   = field(compare=False)
    rvol:         float = field(compare=False)
    trigger_bar:  pd.Timestamp = field(compare=False)
    meta:         dict  = field(compare=False, default_factory=dict)


# ── Shared indicator cache (recomputed once per tick call) ────────────────────

def _build_indicator_frame(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute all indicators needed by the four strategies in a single pass.
    Returns an augmented copy of df (today's bars only).
    """
    if df.empty:
        return df

    latest_date = df["time"].dt.date.max()
    today       = df[df["time"].dt.date == latest_date].copy().reset_index(drop=True)

    # VWAP + standard deviation bands (+1/-1, +2/-2 sigma)
    # Bands serve as institutional reference levels: price at +2σ is extended;
    # price at -1σ during a downtrend is a clean re-entry zone.
    _vwap_frame = compute_vwap_bands(today, num_stds=(1, 2))
    today["vwap"]        = _vwap_frame["vwap"].ffill()
    today["vwap_upper1"] = _vwap_frame["vwap_upper1"].ffill()
    today["vwap_lower1"] = _vwap_frame["vwap_lower1"].ffill()
    today["vwap_upper2"] = _vwap_frame["vwap_upper2"].ffill()
    today["vwap_lower2"] = _vwap_frame["vwap_lower2"].ffill()

    # RVOL (true 10-day if df spans multiple days, else 20-bar rolling proxy)
    rvol_series = compute_rvol(df, lookback_days=10)
    today["rvol"] = rvol_series.reindex(today.index).fillna(1.0)

    # EMA50 — long-term trend filter (replaces ema9/ema21 which have been removed)
    today["ema50"] = today["close"].ewm(span=50, adjust=False).mean()

    # ATR (14-bar, used for structure and FVG sizing)
    hl  = today["high"]  - today["low"]
    hcp = (today["high"]  - today["close"].shift(1)).abs()
    lcp = (today["low"]   - today["close"].shift(1)).abs()
    tr  = pd.concat([hl, hcp, lcp], axis=1).max(axis=1)
    today["atr"] = tr.ewm(span=14, adjust=False).mean()

    # 100-bar volume SMA — used by session-window evaluators as a cleaner
    # volume gate than raw RVOL (rolling intraday reference, not cross-day).
    # 100 bars on 1-min = ~100 min of context, equivalent to the old 20-bar
    # SMA on 5-min bars.  min_periods=20 so the gate waits for at least 20
    # minutes of data before activating (avoids false spikes at the open).
    today["vol_sma20"] = today["volume"].rolling(100, min_periods=20).mean()

    return today


# ── Dynamic RVOL threshold ────────────────────────────────────────────────────

def _get_dynamic_rvol_threshold(
    bar_min: int,
    close: float,
    or_low: "float | None",
    vwap: "float | None",
    strategy_id: str = "",
    msa_confirmed: bool = False,
) -> float:
    """
    Return the RVOL gate threshold for the current market context.

    Priority order (first match wins):

    1. msa_confirmed=True — MarketStructureAnalyzer confirmed a valid structural
       sequence (Lower High / Lower Low bearish, or Higher Low / Higher High
       bullish). Structure IS the edge; drop gate to 0.5× so afternoon setups
       with genuine market structure are never RVOL-starved.

    2. CHAN_BREAK — trendline confluence; fixed 1.2×.

    3. Mid-day bleed (10:30–13:00, price < OR Low AND < VWAP) — confirmed bias,
       slow-bleed conditions; relax to 1.0×.

    4. Default — ORB_RVOL_THRESHOLD from config (1.2×).
    """
    # ── Compute threshold ─────────────────────────────────────────────────────
    if msa_confirmed:
        # Confirmed structure IS the primary edge — volume is secondary.
        # Afternoon/slow sessions naturally print 0.7–0.9× RVOL even on
        # high-conviction structural breaks.  Use 0.75× so the gate only
        # blocks truly dead-tape bars (e.g. lunch flatlines).
        threshold = 0.75

    elif strategy_id == "CHAN_BREAK":
        threshold = 1.0   # channel touch still needs real participation

    else:
        mid_day = (10 * 60 + 30) <= bar_min <= (13 * 60)
        if (mid_day
                and or_low is not None and close < or_low
                and vwap is not None and close < vwap):
            threshold = 0.75  # confirmed bleed below OR Low + VWAP — tape is directional
        else:
            threshold = ORB_RVOL_THRESHOLD  # default 1.2× for opening strategies

    # ── Time-adaptive absolute floor ─────────────────────────────────────────
    # Opening (≤ 10:30 ET): require real participation (1.0× floor).
    # Midday / afternoon (> 10:30 ET): market naturally thins 20–30%;
    #   0.75× still means real directional flow relative to the time slot.
    #   A strict 1.0× floor after 10:30 blocks nearly every afternoon setup.
    floor = 0.75 if bar_min > (10 * 60 + 30) else 1.0
    return max(threshold, floor)


def _rvol_threshold_reason(
    bar_min: int,
    close: float,
    or_low: "float | None",
    vwap: "float | None",
    strategy_id: str = "",
    msa_confirmed: bool = False,
) -> str:
    """
    Companion to _get_dynamic_rvol_threshold() — returns WHICH of the 4
    priority branches produced the threshold, in plain English, for the
    audit log / Signal.meta. Logging-only: deliberately a separate
    function rather than changing _get_dynamic_rvol_threshold()'s return
    type, so this transparency addition can never alter the actual
    gating decision any of the 8 strategies make. Mirrors the same
    priority order exactly — keep both functions' branch conditions in
    sync if either one changes.

    FIX 2026-06-21 (complexity audit): the real gate each strategy uses
    was previously invisible unless you traced into each evaluator by
    hand — that opacity is exactly what produced an earlier user-visible
    bug (a displayed "needs ≥1.3×" that didn't match what the code
    actually required). Surfacing the reason directly in the audit log
    means that mismatch class can't recur silently.
    """
    if msa_confirmed:
        return "structure confirmed (MSA) — relaxed to 0.75× (afternoon thinning expected)"
    if strategy_id == "CHAN_BREAK":
        return "CHAN_BREAK — 1.0× (channel touch needs real participation)"
    mid_day = (10 * 60 + 30) <= bar_min <= (13 * 60)
    if (mid_day and or_low is not None and close < or_low
            and vwap is not None and close < vwap):
        return "mid-day bleed (below OR Low + VWAP) — relaxed to 0.75×"
    return "default session threshold (ORB_RVOL_THRESHOLD)"


# ── Recent FVG detection helper ───────────────────────────────────────────────

def _has_recent_fvg(today: pd.DataFrame, direction: str, lookback: int = 20) -> bool:
    """
    Return True if there is a confirmed Fair Value Gap of the correct direction
    within the last `lookback` bars of today's session.

    Used by BOS_MSS to require structural imbalance evidence before firing a
    market-structure-shift signal — prevents false BOS signals in choppy price.

    A bullish FVG:  bar[k-1].low  > bar[k+1].high  (gap above bar[k+1], below bar[k-1])
    A bearish FVG:  bar[k-1].high < bar[k+1].low   (gap below bar[k+1], above bar[k-1])

    Gap must exist at least 1 bar back (can't use the very last bar as bar[k+1]).
    """
    n = len(today)
    if n < 3:
        return False

    window = min(lookback, n - 2)     # need bar[k+1] to exist
    for k in range(n - 2, max(n - 2 - window, 1), -1):
        if k - 1 < 0:
            break
        b_prev   = today.iloc[k - 1]
        b_next   = today.iloc[k + 1]

        if direction == "bullish":
            # Gap: b_prev.low > b_next.high  (price jumped up; gap below b_prev.low)
            if float(b_prev["low"]) > float(b_next["high"]):
                return True
        else:  # bearish
            # Gap: b_prev.high < b_next.low  (price dropped; gap above b_prev.high)
            if float(b_prev["high"]) < float(b_next["low"]):
                return True

    return False


# ═══════════════════════════════════════════════════════════════════════════════
# Strategy 1 — Institutional ORB  (Strategy_ID: INST_ORB)
# ═══════════════════════════════════════════════════════════════════════════════

def _eval_inst_orb(today: pd.DataFrame) -> Optional[Signal]:
    """
    Institutional Morning ORB — upgraded with MarketStructureAnalyzer context.

    Session window: 09:45–10:30 ET.
    The Opening Range is the 15-minute high/low spanning 09:30, 09:35, and
    09:40. Breakout signals are blocked until 09:45 when the range is complete.
    Volume gate uses vol_sma20 × 1.5 alongside RVOL ≥ 150% for a
    double-confirmed high-activity confirmation.
    MSA structural guard prevents entry when price has already made an
    extended move away from the OR (overextended structure = stale signal).

    Gates (all must pass):
      1. Session: 09:45–10:30 ET  (15-min range complete at 09:45)
      2. Price closes outside OR High / OR Low
      3. RVOL ≥ 150% (10-day same-slot RVOL) — lowered from 200% to capture
         quality setups that institutional flow doesn't always spike to 2×
      4. Current Volume > vol_sma20 × 1.5  (raw bar volume vs 100-bar SMA)
      5. VWAP alignment (bullish above VWAP, bearish below)
      6. MSA: trend is not already overextended in the breakout direction
         (catches situations where price has already run 5–6 SH/SL extensions
          and the ORB signal would be a late-entry chase)
    """
    if len(today) < 2:
        return None

    or_info = get_opening_range(today)
    if or_info is None:
        return None

    or_high = or_info["high"]
    or_low  = or_info["low"]

    # Build MSA once for the full today-frame (5-bar lookback)
    msa   = MarketStructureAnalyzer(today)
    trend = msa.classify_trend()

    for idx in range(1, len(today)):
        bar     = today.iloc[idx]
        close   = float(bar["close"])
        vwap    = float(bar["vwap"])     if not pd.isna(bar.get("vwap",     np.nan)) else None
        rvol    = float(bar["rvol"])     if not pd.isna(bar.get("rvol",     np.nan)) else 0.0
        vol     = float(bar["volume"])
        vol_sma = float(bar["vol_sma20"]) if not pd.isna(bar.get("vol_sma20", np.nan)) else 0.0
        bar_min = bar["time"].hour * 60 + bar["time"].minute

        # Gate 1: session window 09:45–10:30 only
        # The 15-min opening range (09:30, 09:35, 09:40) must be fully formed
        # before any breakout can be evaluated. First valid signal bar is 09:45.
        if bar_min < 9 * 60 + 45:
            continue
        if bar_min > 10 * 60 + 30:
            break

        # Gate 2: breakout direction
        if   close > or_high: direction = "bullish"
        elif close < or_low:  direction = "bearish"
        else:                  continue

        # Gate 2b: trend alignment flip
        # If price broke the ORB high but the trend is a confirmed downtrend,
        # this is a FAILED BREAKOUT / fade setup — flip to PUT (bearish).
        # Conversely, a break below ORB low in an uptrend is a failed breakdown
        # — flip to CALL (bullish).  Both are high-probability reversal entries.
        if direction == "bullish" and trend == "downtrend":
            direction = "bearish"
            logger.info(
                "INST_ORB: price above OR high but trend=downtrend — "
                "flipping to bearish PUT (failed breakout fade)"
            )
        elif direction == "bearish" and trend == "uptrend":
            direction = "bullish"
            logger.info(
                "INST_ORB: price below OR low but trend=uptrend — "
                "flipping to bullish CALL (failed breakdown fade)"
            )

        # Gate 3: dynamic RVOL — drops to 1.0× during mid-day bleed, 0.5× when
        # MSA confirms structural trend alignment (LH/LL or HL/HH sequence).
        _msa_ok = (msa.confirmed_lower_high() if direction == "bearish"
                   else msa.confirmed_higher_low())
        _rvol_min = _get_dynamic_rvol_threshold(
            bar_min, close, or_low, vwap, "INST_ORB", msa_confirmed=_msa_ok)
        _rvol_reason = _rvol_threshold_reason(
            bar_min, close, or_low, vwap, "INST_ORB", msa_confirmed=_msa_ok)
        if rvol < _rvol_min:
            logger.debug("INST_ORB %s: RVOL %.2f < %.1f (msa=%s) — skipped",
                         direction, rvol, _rvol_min, _msa_ok)
            continue

        # Gate 4: volume > vol_sma20 × 1.5 (lowered from 2.0 alongside RVOL cut)
        if vol_sma > 0 and vol < vol_sma * 1.5:
            logger.debug("INST_ORB %s: vol %.0f < sma×1.5 (%.0f) — skipped",
                         direction, vol, vol_sma * 1.5)
            continue

        # Gate 5: VWAP alignment
        if vwap is not None:
            if direction == "bullish" and close <= vwap: continue
            if direction == "bearish" and close >= vwap: continue

        # Gate 6: MSA structural guard
        # If price is already in a mature trend extension in the breakout
        # direction (≥ 3 consecutive HH/HL or LH/LL pairs) the ORB is stale.
        # Simple proxy: if trend is already fully aligned AND price has printed
        # a confirmed swing in the breakout direction before this bar, skip.
        if direction == "bullish" and trend == "uptrend":
            last_sh = msa.last_swing_high()
            if last_sh is not None and close > last_sh * 1.005:
                # Price has already extended 0.5% past the most recent SH —
                # chasing a breakout that's already extended.
                logger.debug("INST_ORB bullish: price %.2f overextended past SH %.2f",
                             close, last_sh)
                continue
        if direction == "bearish" and trend == "downtrend":
            last_sl = msa.last_swing_low()
            if last_sl is not None and close < last_sl * 0.995:
                logger.debug("INST_ORB bearish: price %.2f overextended past SL %.2f",
                             close, last_sl)
                continue

        # Confidence: base 0.85 + RVOL bonus + structural alignment bonus
        struct_bonus = 0.04 if (
            (direction == "bullish" and trend in ("uptrend", "consolidation")) or
            (direction == "bearish" and trend in ("downtrend", "consolidation"))
        ) else 0.0
        confidence = min(0.95, 0.85 + (rvol - ORB_RVOL_THRESHOLD) * 0.04 + struct_bonus)

        logger.info(
            "INST_ORB signal: %s RVOL=%.2f vol_ratio=%.1fx trend=%s confidence=%.2f",
            direction, rvol, (vol / vol_sma if vol_sma > 0 else 0), trend, confidence,
        )
        return Signal(
            strategy_id  = "INST_ORB",
            direction    = direction,
            confidence   = confidence,
            rvol         = rvol,
            trigger_bar  = bar["time"],
            meta         = {
                "or_high":      or_high,
                "or_low":       or_low,
                "vwap":         vwap,
                "trend":        trend,
                "vol_ratio":    round(vol / vol_sma, 2) if vol_sma > 0 else None,
                "rvol_gate":        round(_rvol_min, 2),
                "rvol_gate_reason": _rvol_reason,
            },
        )
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# Strategy 2 — Break of Structure / Market Structure Shift  (BOS_MSS)
# ═══════════════════════════════════════════════════════════════════════════════

def _eval_bos_mss(today: pd.DataFrame) -> Optional[Signal]:
    """
    Detects a Break of Structure (BOS) or Market Structure Shift (MSS):

    Bullish BOS  : price makes a Lower Low then breaks the prior Swing High
                   — trend has shifted from bearish to bullish
    Bearish BOS  : price makes a Higher High then breaks the prior Swing Low
                   — trend has shifted from bullish to bearish

    Minimum 6 bars needed to identify swing highs/lows reliably.

    Gates:
      0. Session: 09:45+ ET (need at least 15 min for reliable structure to form)
      1. Swing structure confirmed (LL→BOS high or HH→BOS low)
      2. RVOL ≥ 150% on the break candle (lower bar than ORB — less institutional)
      3. VWAP alignment
      4. Price > EMA50 for bullish; price < EMA50 for bearish (trend filter)

    FIX 2026-06-21 (consistency audit): this used to call its own private
    _find_swings(pivot_bars=2) instead of the shared MarketStructureAnalyzer
    (5-bar lookback) that every other strategy reads. Two different swing
    definitions meant BOS_MSS could see "structure" that AFT_REV/MID_BRK/
    TREND_CONT/CHAN_BREAK would all disagree exists, since they're reading
    the same bars through a different lens. Switched to MSA's swings so all
    structure-dependent strategies agree on what a swing pivot actually is.
    This is a real behavior change, not just a refactor — a 5-bar lookback
    is more conservative than 2-bar, so BOS_MSS will likely fire less often.
    Run through backtester.py before relying on it live.
    _find_swings() itself is untouched — dashboard.py's Live Trading chart
    overlay still uses it for the HH/LH/HL/LL display labels, which is a
    cosmetic concern, not a trading decision.
    """
    if len(today) < 6:
        return None

    last_bar_check = today.iloc[-1]
    bar_min_check  = last_bar_check["time"].hour * 60 + last_bar_check["time"].minute
    # Gate 0: block before 9:45 — less than 15 min of session bars means
    # swing structure detection is unreliable (only 1-2 real pivots at most).
    if bar_min_check < 9 * 60 + 45:
        return None

    # Identify swing highs and lows via the SAME 5-bar MarketStructureAnalyzer
    # every other structure-dependent strategy uses (see fix note above).
    msa    = MarketStructureAnalyzer(today)
    swings = [(s["idx"], s["price"], s["type"]) for s in msa.swings]
    if len(swings) < 3:
        return None

    last_bar  = today.iloc[-1]
    close     = float(last_bar["close"])
    vwap      = float(last_bar["vwap"])  if not pd.isna(last_bar.get("vwap", np.nan)) else None
    rvol      = float(last_bar["rvol"])  if not pd.isna(last_bar.get("rvol", np.nan)) else 0.0
    ema50     = float(last_bar["ema50"]) if not pd.isna(last_bar.get("ema50", np.nan)) else close

    # ── Bullish MSS: look for LL then BOS above prior swing high ─────────────
    lows  = [(i, p, t) for i, p, t in swings if t == "low"]
    highs = [(i, p, t) for i, p, t in swings if t == "high"]

    if len(lows) >= 2 and len(highs) >= 1:
        last_low      = lows[-1][1]
        prev_low      = lows[-2][1]
        prior_hi      = highs[-1][1]
        # Lower Low confirmed + BOS above prior swing high
        if last_low < prev_low and close > prior_hi:
            direction = "bullish"
            # MSS requires: RVOL ≥ 1.5×, VWAP alignment, price > EMA50 (trend filter),
            # AND a confirmed bullish FVG in the recent session (institutional imbalance)
            fvg_confirmed = _has_recent_fvg(today, "bullish")
            if (rvol >= 1.5
                    and (vwap is None or close > vwap)
                    and close > ema50
                    and fvg_confirmed):
                confidence = min(0.88, 0.70 + rvol * 0.06)
                logger.info("BOS_MSS bullish signal RVOL=%.2f conf=%.2f fvg=True", rvol, confidence)
                return Signal(
                    strategy_id = "BOS_MSS",
                    direction   = direction,
                    confidence  = confidence,
                    rvol        = rvol,
                    trigger_bar = last_bar["time"],
                    meta        = {
                        "prior_swing_high": prior_hi,
                        "last_low":         last_low,
                        "prev_low":         prev_low,
                        "vwap":             vwap,
                        "fvg_confirmed":    True,
                    },
                )
            elif not fvg_confirmed:
                logger.debug("BOS_MSS bullish: no confirmed FVG — MSS skipped (requires imbalance)")

    # ── Bearish MSS: look for HH then BOS below prior swing low ──────────────
    if len(highs) >= 2 and len(lows) >= 1:
        last_high     = highs[-1][1]
        prev_high     = highs[-2][1]
        prior_lo      = lows[-1][1]
        # Higher High confirmed + BOS below prior swing low
        if last_high > prev_high and close < prior_lo:
            direction = "bearish"
            fvg_confirmed = _has_recent_fvg(today, "bearish")
            if (rvol >= 1.5
                    and (vwap is None or close < vwap)
                    and close < ema50
                    and fvg_confirmed):
                confidence = min(0.88, 0.70 + rvol * 0.06)
                logger.info("BOS_MSS bearish signal RVOL=%.2f conf=%.2f fvg=True", rvol, confidence)
                return Signal(
                    strategy_id = "BOS_MSS",
                    direction   = direction,
                    confidence  = confidence,
                    rvol        = rvol,
                    trigger_bar = last_bar["time"],
                    meta        = {
                        "prior_swing_low": prior_lo,
                        "last_high":       last_high,
                        "prev_high":       prev_high,
                        "vwap":            vwap,
                        "fvg_confirmed":   True,
                    },
                )
            elif not fvg_confirmed:
                logger.debug("BOS_MSS bearish: no confirmed FVG — MSS skipped (requires imbalance)")

    return None


def _find_swings(df: pd.DataFrame, pivot_bars: int = 2) -> list[tuple[int, float, str]]:
    """
    Return a list of (index, price, 'high'|'low') swing pivot points.
    A swing high is a bar whose high is greater than the `pivot_bars` bars on each side.
    A swing low  is a bar whose low  is less    than the `pivot_bars` bars on each side.
    Used internally by BOS_MSS evaluator (2-bar lookback for responsiveness).
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


# ═══════════════════════════════════════════════════════════════════════════════
# MarketStructureAnalyzer
# Reads price structure using a 5-bar rolling lookback — identical to how a
# human trader manually marks SH / SL pivots on a chart.
# ═══════════════════════════════════════════════════════════════════════════════

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

    Swings are detected once (lazy) and cached for the lifetime of the object.
    """

    LOOKBACK: int = 5   # bars on each side — wide enough to filter noise,
                         # tight enough to be responsive intraday

    def __init__(self, df: pd.DataFrame) -> None:
        self._df     = df.reset_index(drop=True)
        self._swings: list[dict] | None = None   # lazy cache

    # ── Swing detection ───────────────────────────────────────────────────────

    def _detect_swings(self) -> list[dict]:
        """
        5-bar lookback pivot detection.
        A SH is a bar whose 'high' exceeds the 5 bars before AND after it.
        A SL is a bar whose 'low'  is below  the 5 bars before AND after it.
        Returns chronologically sorted list of dicts:
          { idx, price, type ('high'|'low'), time }
        """
        pivots: list[dict] = []
        df = self._df
        n  = len(df)
        lb = self.LOOKBACK

        for i in range(lb, n - lb):
            bar   = df.iloc[i]
            left  = df.iloc[i - lb : i]
            right = df.iloc[i + 1 : i + lb + 1]

            if bar["high"] > left["high"].max() and bar["high"] > right["high"].max():
                pivots.append({
                    "idx":   i,
                    "price": float(bar["high"]),
                    "type":  "high",
                    "time":  bar["time"],
                })
            if bar["low"] < left["low"].min() and bar["low"] < right["low"].min():
                pivots.append({
                    "idx":   i,
                    "price": float(bar["low"]),
                    "type":  "low",
                    "time":  bar["time"],
                })

        pivots.sort(key=lambda p: p["idx"])
        return pivots

    @property
    def swings(self) -> list[dict]:
        """Cached swing list — computed once per MSA instance."""
        if self._swings is None:
            self._swings = self._detect_swings()
        return self._swings

    # ── Convenience accessors ─────────────────────────────────────────────────

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

    # ── Trend classification ──────────────────────────────────────────────────

    def classify_trend(self) -> str:
        """
        Compare the last two swing highs and the last two swing lows:
          HH + HL → "uptrend"
          LH + LL → "downtrend"
          otherwise → "consolidation"
        Requires at least 2 highs and 2 lows to classify; falls back to
        "consolidation" when structure is too young.
        """
        highs = self._highs()
        lows  = self._lows()

        if len(highs) < 2 or len(lows) < 2:
            return "consolidation"

        hh = highs[-1]["price"] > highs[-2]["price"]   # Higher High
        hl = lows[-1]["price"]  > lows[-2]["price"]    # Higher Low
        lh = highs[-1]["price"] < highs[-2]["price"]   # Lower High
        ll = lows[-1]["price"]  < lows[-2]["price"]    # Lower Low

        if hh and hl:
            return "uptrend"
        if lh and ll:
            return "downtrend"
        return "consolidation"

    # ── Structural confirmation helpers ───────────────────────────────────────

    def confirmed_higher_low(self) -> bool:
        """True when the most recent SL is above the previous SL (HL confirmed)."""
        lows = self._lows()
        return len(lows) >= 2 and lows[-1]["price"] > lows[-2]["price"]

    def confirmed_lower_high(self) -> bool:
        """True when the most recent SH is below the previous SH (LH confirmed)."""
        highs = self._highs()
        return len(highs) >= 2 and highs[-1]["price"] < highs[-2]["price"]


# ═══════════════════════════════════════════════════════════════════════════════
# Strategy 3 — VWAP Pullback  (VWAP_PB)
# ═══════════════════════════════════════════════════════════════════════════════

def _eval_vwap_pullback(today: pd.DataFrame) -> Optional[Signal]:
    """
    Trend-continuation pullback to VWAP:

    Bullish: EMA9 > EMA21 > EMA50 (uptrend); price dips to VWAP then closes
             back above VWAP on the current bar; RVOL ≥ 150%.

    Bearish: EMA9 < EMA21 < EMA50 (downtrend); price bounces to VWAP then
             closes back below VWAP; RVOL ≥ 150%.

    This fires intraday from 09:45 onwards (skip first 15 min of chaos).
    Confidence is modulated by how cleanly price respected VWAP (proximity).
    """
    if len(today) < 8:
        return None

    # Need at least 2 consecutive bars to see the "touch then reverse" pattern
    prev = today.iloc[-2]
    curr = today.iloc[-1]

    bar_min = curr["time"].hour * 60 + curr["time"].minute
    if bar_min < 9 * 60 + 45:
        return None   # too early — skip the opening chaos bars

    c_close = float(curr["close"])
    c_vwap  = float(curr["vwap"])  if not pd.isna(curr.get("vwap", np.nan)) else None
    c_rvol  = float(curr["rvol"])  if not pd.isna(curr.get("rvol", np.nan)) else 0.0
    c_ema50 = float(curr["ema50"]) if not pd.isna(curr.get("ema50", np.nan)) else c_close

    p_low   = float(prev["low"])
    p_high  = float(prev["high"])
    p_vwap  = float(prev["vwap"]) if not pd.isna(prev.get("vwap", np.nan)) else None

    if c_vwap is None or p_vwap is None:
        return None

    # ── MSA — computed once, used by both direction branches ─────────────────
    _msa_vwap    = MarketStructureAnalyzer(today)
    _msa_ok_bull = _msa_vwap.confirmed_higher_low()   # bullish structure confirmed
    _msa_ok_bear = _msa_vwap.confirmed_lower_high()   # bearish structure confirmed

    # ── Bullish pullback ──────────────────────────────────────────────────────
    # Trend filter: price AND vwap both above EMA50.
    # Entry condition: previous bar dipped to VWAP, current bar reclaimed it.
    # RVOL gate: drops to 0.5× when confirmed_higher_low() so mid-day bounces
    # at lower-than-ORB volume still qualify when structure is confirmed.
    _rvol_min_bull = _get_dynamic_rvol_threshold(
        bar_min, c_close, None, c_vwap, "VWAP_PB", msa_confirmed=_msa_ok_bull)
    if (c_close > c_ema50 and          # price above long-term anchor
        c_vwap > c_ema50 and           # VWAP itself trending up — uptrend context
        p_low <= p_vwap and            # previous bar touched / crossed below VWAP
        c_close > c_vwap and           # current bar reclaimed VWAP
        c_rvol >= _rvol_min_bull):
        # Proximity score: tighter VWAP touch → higher confidence
        proximity  = max(0.0, 1.0 - abs(p_low - p_vwap) / max(p_vwap * 0.005, 0.01))
        confidence = min(0.82, 0.60 + proximity * 0.15 + min(c_rvol - _rvol_min_bull, 1.0) * 0.07)
        logger.info(
            "VWAP_PB bullish signal RVOL=%.2f (min=%.2f msa=%s) conf=%.2f",
            c_rvol, _rvol_min_bull, _msa_ok_bull, confidence,
        )
        return Signal(
            strategy_id = "VWAP_PB",
            direction   = "bullish",
            confidence  = confidence,
            rvol        = c_rvol,
            trigger_bar = curr["time"],
            meta        = {
                "vwap":           c_vwap,
                "ema50":          c_ema50,
                "prev_low":       p_low,
                "vwap_touch":     p_low <= p_vwap,
                "entry_bar_low":  float(curr["low"]),   # structural stop reference for CALL
                "msa_confirmed":  _msa_ok_bull,
                "rvol_gate":        round(_rvol_min_bull, 2),
                "rvol_gate_reason": _rvol_threshold_reason(
                    bar_min, c_close, None, c_vwap, "VWAP_PB", msa_confirmed=_msa_ok_bull),
            },
        )

    # ── Bearish pullback ──────────────────────────────────────────────────────
    # Pattern: price below EMA50 + VWAP, prev bar bounced up to VWAP from below,
    # current bar closes back below VWAP → confirmed VWAP rejection short.
    # Stop reference: HIGH of the entry candle (the LH rejection bar).
    # RVOL gate: drops to 0.5× when confirmed_lower_high() — captures the
    # 10:00–10:30 AM AAPL-style LH rejection that stalls at mid-session RVOL.
    _rvol_min_bear = _get_dynamic_rvol_threshold(
        bar_min, c_close, None, c_vwap, "VWAP_PB", msa_confirmed=_msa_ok_bear)
    if (c_close < c_ema50 and          # price below long-term anchor
        c_vwap < c_ema50 and           # VWAP itself trending down — downtrend context
        p_high >= p_vwap and           # previous bar bounced up to VWAP from below
        c_close < c_vwap and           # current bar rejected back below VWAP
        c_rvol >= _rvol_min_bear):
        proximity   = max(0.0, 1.0 - abs(p_high - p_vwap) / max(p_vwap * 0.005, 0.01))
        confidence  = min(0.82, 0.60 + proximity * 0.15 + min(c_rvol - _rvol_min_bear, 1.0) * 0.07)
        logger.info(
            "VWAP_PB bearish signal RVOL=%.2f (min=%.2f msa=%s) conf=%.2f",
            c_rvol, _rvol_min_bear, _msa_ok_bear, confidence,
        )
        return Signal(
            strategy_id = "VWAP_PB",
            direction   = "bearish",
            confidence  = confidence,
            rvol        = c_rvol,
            trigger_bar = curr["time"],
            meta        = {
                "vwap":            c_vwap,
                "ema50":           c_ema50,
                "prev_high":       p_high,
                "vwap_touch":      p_high >= p_vwap,
                "entry_bar_high":  float(curr["high"]),   # structural stop: PUT exits if reclaims this
                "msa_confirmed":   _msa_ok_bear,
                "rvol_gate":        round(_rvol_min_bear, 2),
                "rvol_gate_reason": _rvol_threshold_reason(
                    bar_min, c_close, None, c_vwap, "VWAP_PB", msa_confirmed=_msa_ok_bear),
            },
        )

    return None


# ═══════════════════════════════════════════════════════════════════════════════
# Strategy 4 — Fair Value Gap  (FVG)
# ═══════════════════════════════════════════════════════════════════════════════

def _eval_fvg(today: pd.DataFrame) -> Optional[Signal]:
    """
    Fair Value Gap (FVG) — also called an imbalance or liquidity void.

    A three-candle imbalance:
      Bullish FVG: bar[i-1].low > bar[i+1].high  →  gap between bar-2 high
                   and bar-0 low is unfilled; price re-enters it bullishly.
      Bearish FVG: bar[i-1].high < bar[i+1].low  →  gap; price re-enters bearishly.

    Entry trigger: the most recent bar closes INTO the gap (retest / fill attempt)
    on the correct side.  Gap must be ≥ 0.5× ATR to be meaningful.

    Gates:
      1. Gap width ≥ 0.5 × ATR14
      2. RVOL ≥ 150% on the retest candle
      3. VWAP on the correct side
    """
    # Need at least 6 bars: 3 to form the gap + at least 1 subsequent bar to retest
    if len(today) < 6:
        return None

    last_bar = today.iloc[-1]
    bar_min  = last_bar["time"].hour * 60 + last_bar["time"].minute
    # Block before 9:45: gaps formed in the first 15 minutes are pre-structure
    # noise (opening auction imbalance, not institutional FVGs).
    if bar_min < 9 * 60 + 45:
        return None

    c_close  = float(last_bar["close"])
    c_vwap   = float(last_bar["vwap"])  if not pd.isna(last_bar.get("vwap", np.nan)) else None
    c_rvol   = float(last_bar["rvol"])  if not pd.isna(last_bar.get("rvol", np.nan)) else 0.0
    atr      = float(last_bar["atr"])   if not pd.isna(last_bar.get("atr", np.nan))  else 0.0

    # Scan the recent window for an unmitigated FVG (look back up to 20 bars)
    look_back = min(20, len(today) - 2)
    for k in range(look_back, 0, -1):
        # Trio: bar[k-1], bar[k] (impulse), bar[k+1]
        if k - 1 < 0 or k + 1 >= len(today):
            continue
        b_prev   = today.iloc[k - 1]
        b_middle = today.iloc[k]
        b_next   = today.iloc[k + 1]

        gap_low  = None
        gap_high = None
        direction = None

        # Bullish FVG: b_prev.low > b_next.high  (gap above b_next, below b_prev)
        if float(b_prev["low"]) > float(b_next["high"]):
            gap_low   = float(b_next["high"])
            gap_high  = float(b_prev["low"])
            direction = "bullish"

        # Bearish FVG: b_prev.high < b_next.low
        elif float(b_prev["high"]) < float(b_next["low"]):
            gap_low   = float(b_prev["high"])
            gap_high  = float(b_next["low"])
            direction = "bearish"

        if direction is None:
            continue

        gap_width = gap_high - gap_low
        if atr > 0 and gap_width < 0.5 * atr:
            continue   # gap too small — noise, not structure

        # Check if the current close is INSIDE the gap (retest)
        if not (gap_low <= c_close <= gap_high):
            continue

        # Gate: RVOL ≥ 150%
        if c_rvol < 1.5:
            logger.debug("FVG %s: RVOL %.2f < 1.5 — skipped", direction, c_rvol)
            continue

        # Gate: VWAP alignment
        if c_vwap is not None:
            if direction == "bullish" and c_close < c_vwap: continue
            if direction == "bearish" and c_close > c_vwap: continue

        # Gap width relative to ATR scales confidence
        gap_ratio  = gap_width / atr if atr > 0 else 1.0
        confidence = min(0.80, 0.55 + min(gap_ratio, 2.0) * 0.10 + min(c_rvol - 1.5, 1.0) * 0.05)

        logger.info(
            "FVG %s signal gap=[%.4f–%.4f] RVOL=%.2f conf=%.2f",
            direction, gap_low, gap_high, c_rvol, confidence,
        )
        return Signal(
            strategy_id = "FVG",
            direction   = direction,
            confidence  = confidence,
            rvol        = c_rvol,
            trigger_bar = last_bar["time"],
            meta        = {
                "gap_low":    gap_low,
                "gap_high":   gap_high,
                "gap_width":  gap_width,
                "atr":        atr,
                "vwap":       c_vwap,
                "formed_bar": b_middle["time"],
            },
        )

    return None


# ═══════════════════════════════════════════════════════════════════════════════
# Strategy 5 — Mid-Day Breakdown  (MID_BRK)
# Session: 10:30–13:00 ET | Direction: bearish (SHORT/PUT)
# ═══════════════════════════════════════════════════════════════════════════════

def _eval_midday_breakdown(today: pd.DataFrame) -> Optional[Signal]:
    """
    Mid-Day Structural Breakdown — fires during the 10:30–13:00 consolidation
    window when institutional momentum has finished and price rolls over.

    Human-trader read:
      After the opening range plays out, institutions stop accumulating.
      If price re-enters the OR from above (collapses below OR Low) with VWAP
      as resistance AND the structure has already printed a Lower High (price
      attempted a rally and got rejected), the bias flips strongly bearish.

    Gates (all must pass):
      1. Session: 10:30–13:00 ET
      2. Price < OR Low  (failed to hold the range — breakdown confirmed)
      3. Price < VWAP    (institutional selling pressure overhead)
      4. MSA: confirmed Lower High printed  (prior rally attempt rejected = LH)
      5. Volume > vol_sma20 × 1.5  (breakdown must be accompanied by real selling)

    Confidence modulated by: RVOL level + trend alignment (downtrend bonus).
    """
    if len(today) < 10:
        return None

    last_bar = today.iloc[-1]
    bar_min  = last_bar["time"].hour * 60 + last_bar["time"].minute

    # Gate 1: session window 10:30–13:00
    if not (10 * 60 + 30 <= bar_min <= 13 * 60):
        return None

    or_info = get_opening_range(today)
    if or_info is None:
        return None

    close    = float(last_bar["close"])
    vwap     = float(last_bar["vwap"])      if not pd.isna(last_bar.get("vwap",     np.nan)) else None
    rvol     = float(last_bar["rvol"])      if not pd.isna(last_bar.get("rvol",     np.nan)) else 0.0
    vol      = float(last_bar["volume"])
    vol_sma  = float(last_bar["vol_sma20"]) if not pd.isna(last_bar.get("vol_sma20", np.nan)) else 0.0
    or_low   = or_info["low"]
    or_high  = or_info["high"]

    # Gate 2: price below OR Low
    if close >= or_low:
        logger.debug("MID_BRK: close %.2f >= or_low %.2f — no breakdown", close, or_low)
        return None

    # Gate 3: price below VWAP
    if vwap is not None and close >= vwap:
        logger.debug("MID_BRK: close %.2f >= vwap %.2f — no VWAP resistance", close, vwap)
        return None

    # Gate 4: MSA — confirmed Lower High (rally attempt was rejected)
    msa = MarketStructureAnalyzer(today)
    if not msa.confirmed_lower_high():
        logger.debug("MID_BRK: no confirmed LH in structure — skipped")
        return None

    # Gate 5: volume confirms the selling
    if vol_sma > 0 and vol < vol_sma * 1.5:
        logger.debug("MID_BRK: vol %.0f < sma20×1.5 (%.0f) — skipped", vol, vol_sma * 1.5)
        return None

    # Gate 6: dynamic RVOL — confirmed LH already proven above (Gate 4 passed),
    # so msa_confirmed=True here; threshold drops to 0.5× for MID_BRK.
    _rvol_min = _get_dynamic_rvol_threshold(
        bar_min, close, or_low, vwap, "MID_BRK", msa_confirmed=True)
    if rvol < _rvol_min:
        logger.debug("MID_BRK: RVOL %.2f < %.1f (msa confirmed) — skipped", rvol, _rvol_min)
        return None

    # Classify trend for confidence bonus
    trend       = msa.classify_trend()
    trend_bonus = 0.05 if trend == "downtrend" else 0.0

    # Distance below OR Low as a magnitude indicator — wider breakdown = higher conf
    breakdown_pct = (or_low - close) / or_low
    mag_bonus     = min(0.04, breakdown_pct * 5)

    confidence = min(0.86, 0.65 + min(rvol - 1.0, 2.0) * 0.04 + trend_bonus + mag_bonus)

    logger.info(
        "MID_BRK bearish signal close=%.2f or_low=%.2f RVOL=%.2f trend=%s conf=%.2f",
        close, or_low, rvol, trend, confidence,
    )
    return Signal(
        strategy_id = "MID_BRK",
        direction   = "bearish",
        confidence  = confidence,
        rvol        = rvol,
        trigger_bar = last_bar["time"],
        meta        = {
            "or_low":         or_low,
            "or_high":        or_high,
            "vwap":           vwap,
            "trend":          trend,
            "lh_confirmed":   True,
            "breakdown_pct":  round(breakdown_pct * 100, 2),
            "rvol_gate":        round(_rvol_min, 2),
            "rvol_gate_reason": _rvol_threshold_reason(
                bar_min, close, or_low, vwap, "MID_BRK", msa_confirmed=True),
        },
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Strategy 6 — Afternoon Reversal  (AFT_REV)
# Session: 13:00–15:30 ET | Direction: bullish
# ═══════════════════════════════════════════════════════════════════════════════

def _eval_afternoon_reversal(today: pd.DataFrame) -> Optional[Signal]:
    """
    Afternoon Structural Reversal — fires during 13:00–15:30 when a prior
    downtrend shows the first confirmed structural shift (HL + SH breakout).

    Human-trader read:
      After a mid-day sell-off, smart money begins accumulating into weakness.
      The first sign is price making a Higher Low (stops selling lower) followed
      by a break above the most recent Swing High (buyers take control).
      This is NOT a mean-reversion fade — it requires structural proof, not just
      "price bounced from a level."

    Gates (all must pass):
      1. Session: 13:00–15:30 ET
      2. MSA: confirmed Higher Low printed  (HL = buyers defended a higher base)
      3. Price closes above the previous Swing High (SH breakout = BOS bullish)
      4. Volume > vol_sma20 × 1.2  (lower bar than morning — afternoon is quieter)
      5. Optional bonus: price > VWAP  (adds to confidence, not a hard block)

    Confidence modulated by: RVOL, VWAP alignment, magnitude of SH breakout.
    """
    if len(today) < 12:
        return None

    last_bar = today.iloc[-1]
    bar_min  = last_bar["time"].hour * 60 + last_bar["time"].minute

    # Gate 1: session window 13:00–15:30
    if not (13 * 60 <= bar_min <= 15 * 60 + 30):
        return None

    close    = float(last_bar["close"])
    vwap     = float(last_bar["vwap"])      if not pd.isna(last_bar.get("vwap",     np.nan)) else None
    rvol     = float(last_bar["rvol"])      if not pd.isna(last_bar.get("rvol",     np.nan)) else 0.0
    vol      = float(last_bar["volume"])
    vol_sma  = float(last_bar["vol_sma20"]) if not pd.isna(last_bar.get("vol_sma20", np.nan)) else 0.0

    # Gate 4a: minimum RVOL ≥ 1.0 — afternoon is quieter but sub-average volume
    # means no institutional participation; the confidence formula would go negative.
    if rvol < 1.0:
        logger.debug("AFT_REV: RVOL %.2f < 1.0 — no institutional participation", rvol)
        return None

    # Gate 4b: absolute volume vs 20-bar SMA (cheap check before building MSA)
    if vol_sma > 0 and vol < vol_sma * 1.2:
        logger.debug("AFT_REV: vol %.0f < sma20×1.2 (%.0f) — skipped", vol, vol_sma * 1.2)
        return None

    # Build MSA
    msa = MarketStructureAnalyzer(today)

    # Gate 2: confirmed Higher Low (structure is shifting bullish)
    if not msa.confirmed_higher_low():
        logger.debug("AFT_REV: no confirmed HL — skipped")
        return None

    # Gate 3: price closes above the MOST RECENT swing high — this is the BOS.
    # In a downtrend, swings are: SH1 (session peak) → LH2 (mid-day lower high).
    # Resistance to break = the LH2 = last_swing_high().
    # prev_swing_high() would be the old session high — breaking that would mean
    # making new session highs, far too strict for an afternoon reversal setup.
    prev_sh = msa.last_swing_high()
    if prev_sh is None:
        logger.debug("AFT_REV: no swing high detected — skipped")
        return None

    if close <= prev_sh:
        logger.debug("AFT_REV: close %.2f <= last SH %.2f — no BOS yet", close, prev_sh)
        return None

    # Confidence components
    vwap_bonus     = 0.05 if (vwap is not None and close > vwap) else 0.0
    breakout_mag   = (close - prev_sh) / prev_sh          # how far past the SH
    mag_bonus      = min(0.04, breakout_mag * 10)         # capped at +4%
    trend          = msa.classify_trend()
    # A consolidation trend transitioning to bullish is the ideal setup;
    # an already-established uptrend gives a smaller bonus (could be late).
    trend_bonus    = 0.03 if trend == "consolidation" else (0.01 if trend == "uptrend" else 0.0)

    confidence = min(0.84, 0.62 + min(rvol - 1.0, 2.0) * 0.05
                     + vwap_bonus + mag_bonus + trend_bonus)

    logger.info(
        "AFT_REV bullish signal close=%.2f prev_sh=%.2f RVOL=%.2f trend=%s conf=%.2f",
        close, prev_sh, rvol, trend, confidence,
    )
    return Signal(
        strategy_id = "AFT_REV",
        direction   = "bullish",
        confidence  = confidence,
        rvol        = rvol,
        trigger_bar = last_bar["time"],
        meta        = {
            "prev_swing_high":  prev_sh,
            "hl_confirmed":     True,
            "trend":            trend,
            "vwap":             vwap,
            "breakout_pct":     round(breakout_mag * 100, 2),
        },
    )



# ═══════════════════════════════════════════════════════════════════════════════
# Strategy 7 — Trend Continuation  (TREND_CONT)
# Session: 09:45–14:30 ET | Direction: both
# ═══════════════════════════════════════════════════════════════════════════════

def _eval_trend_cont(today: pd.DataFrame) -> Optional[Signal]:
    """
    Trend Continuation — LH Re-entry (bearish) or HL Re-entry (bullish).

    Expert context: the best entries of the day are almost never the first
    breakout candle — they're the second and third entries AFTER the trend has
    been proven.  Once a downtrend prints 2+ consecutive LH+LL pairs, every
    Lower High is a gift: institutions gave you a better price to short.
    Same logic inverted for uptrends (Higher Lows).

    Human-trader read:
      "Price bounced but couldn't make a new high. That failed rally is the LH.
       The moment it starts rolling back over — that's my entry. I already know
       the trend. I'm not guessing. The structure told me."

    Detection:
      1. MSA confirms downtrend (LH+LL) or uptrend (HH+HL)
      2. Most recent MSA swing high is a LH  (lower than the prior SH)
         — or most recent swing low is a HL (higher than the prior SL)
      3. The LH/HL swing must be within the last 10 bars (fresh, not stale)
      4. Current bar closes BELOW the LH close (bearish roll-over confirmed)
         or ABOVE the HL close (bullish recovery confirmed)
      5. Price remains on the correct side of VWAP
      6. RVOL ≥ 1.2× — trend already confirmed, institutional threshold not needed

    Confidence: 0.65–0.82 (below INST_ORB but above pure pullback setups).
    """
    if len(today) < 20:
        return None

    last_bar = today.iloc[-1]
    bar_min  = last_bar["time"].hour * 60 + last_bar["time"].minute

    # Gate 1: session window 09:45–14:30 ET
    if not (9 * 60 + 45 <= bar_min <= 14 * 60 + 30):
        return None

    rvol  = float(last_bar["rvol"])  if not pd.isna(last_bar.get("rvol",  np.nan)) else 0.0
    vwap  = float(last_bar["vwap"])  if not pd.isna(last_bar.get("vwap",  np.nan)) else None
    close = float(last_bar["close"])

    # Gate 2: RVOL ≥ 1.2× (lower than ORB threshold — trend already proven)
    if rvol < 1.2:
        logger.debug("TREND_CONT: RVOL %.2f < 1.2 — skipped", rvol)
        return None

    msa   = MarketStructureAnalyzer(today)
    trend = msa.classify_trend()
    highs = msa._highs()   # list of dicts: {idx, price, type, time}
    lows  = msa._lows()
    curr_idx = len(today) - 1

    # ── BEARISH: downtrend + LH re-entry ────────────────────────────────────
    if trend == "downtrend" and msa.confirmed_lower_high() and len(highs) >= 2:
        lh        = highs[-1]     # most recent swing high = the Lower High
        prior_sh  = highs[-2]
        bars_ago  = curr_idx - lh["idx"]

        # Gate 3: LH must be recent (within 20 bars) — stale LHs become noise
        # Widened from 10→20: 10 min was too tight for gradual rollover setups
        # where close-below-LH confirmation lags the swing by 10-15 bars.
        if bars_ago > 20:
            logger.debug("TREND_CONT bearish: LH is %d bars old (> 20) — stale", bars_ago)
        else:
            # Gate 4: current close below the LH bar's close = roll-over confirmed
            lh_bar_close = float(today.iloc[lh["idx"]]["close"])
            if close < lh_bar_close:
                # Gate 5: VWAP — price must remain below VWAP for bearish bias
                if vwap is None or close < vwap:
                    # Magnitude of the LH relative to prior SH — deeper LH = stronger signal
                    lh_depth_pct = (prior_sh["price"] - lh["price"]) / prior_sh["price"]
                    depth_bonus  = min(0.06, lh_depth_pct * 20)
                    rvol_bonus   = min(0.08, (rvol - 1.2) * 0.06)
                    confidence   = min(0.82, 0.65 + rvol_bonus + depth_bonus)
                    logger.info(
                        "TREND_CONT bearish LH re-entry: prior_SH=%.2f LH=%.2f "
                        "close=%.2f RVOL=%.2f bars_ago=%d conf=%.2f",
                        prior_sh["price"], lh["price"], close, rvol, bars_ago, confidence,
                    )
                    return Signal(
                        strategy_id = "TREND_CONT",
                        direction   = "bearish",
                        trigger_bar = last_bar["time"],
                        confidence  = confidence,
                        rvol        = rvol,
                        meta        = {
                            "trigger":    "lh_reentry",
                            "lh_price":   lh["price"],
                            "prior_sh":   prior_sh["price"],
                            "bars_ago":   bars_ago,
                            "lh_depth_pct": round(lh_depth_pct * 100, 2),
                        },
                    )
                else:
                    logger.debug("TREND_CONT bearish: close %.2f >= vwap %.2f", close, vwap)
            else:
                logger.debug(
                    "TREND_CONT bearish: close %.2f >= lh_close %.2f — not rolling over yet",
                    close, lh_bar_close,
                )

    # ── BULLISH: uptrend + HL re-entry ──────────────────────────────────────
    if trend == "uptrend" and msa.confirmed_higher_low() and len(lows) >= 2:
        hl       = lows[-1]      # most recent swing low = the Higher Low
        prior_sl = lows[-2]
        bars_ago = curr_idx - hl["idx"]

        if bars_ago > 20:
            logger.debug("TREND_CONT bullish: HL is %d bars old (> 20) — stale", bars_ago)
        else:
            hl_bar_close = float(today.iloc[hl["idx"]]["close"])
            if close > hl_bar_close:
                if vwap is None or close > vwap:
                    hl_rise_pct  = (hl["price"] - prior_sl["price"]) / prior_sl["price"]
                    rise_bonus   = min(0.06, hl_rise_pct * 20)
                    rvol_bonus   = min(0.08, (rvol - 1.2) * 0.06)
                    confidence   = min(0.82, 0.65 + rvol_bonus + rise_bonus)
                    logger.info(
                        "TREND_CONT bullish HL re-entry: prior_SL=%.2f HL=%.2f "
                        "close=%.2f RVOL=%.2f bars_ago=%d conf=%.2f",
                        prior_sl["price"], hl["price"], close, rvol, bars_ago, confidence,
                    )
                    return Signal(
                        strategy_id = "TREND_CONT",
                        direction   = "bullish",
                        trigger_bar = last_bar["time"],
                        confidence  = confidence,
                        rvol        = rvol,
                        meta        = {
                            "trigger":   "hl_reentry",
                            "hl_price":  hl["price"],
                            "prior_sl":  prior_sl["price"],
                            "bars_ago":  bars_ago,
                            "hl_rise_pct": round(hl_rise_pct * 100, 2),
                        },
                    )
                else:
                    logger.debug("TREND_CONT bullish: close %.2f <= vwap %.2f", close, vwap)

    return None


# ═══════════════════════════════════════════════════════════════════════════════
# Strategy 8 — Channel Trendline Rejection  (CHAN_BREAK)
# Session: 09:45–14:00 ET | Direction: both
# ═══════════════════════════════════════════════════════════════════════════════

def _eval_chan_break(today: pd.DataFrame) -> Optional[Signal]:
    """
    Channel Trendline Rejection — short at descending channel upper line,
    long at ascending channel lower line.

    Expert context: channels are NOT random.  Descending channels form because
    institutions are systematically distributing — they sell each rally to a
    lower high.  The upper trendline IS their sell zone.  When price touches
    that line and closes back below it, you're entering WITH the institution.
    This is one of the highest R:R single-entry setups in intraday trading:
    your stop is a clean channel break, your target is the opposite channel wall.

    Human-trader read:
      "I drew a line through the last two swing highs.  Price just tagged that
       line on the high, but the close is BELOW it.  That's a rejection candle
       exactly at institutional supply.  Short."

    Detection (descending channel — bearish):
      1. Find the 2 most recent MSA swing highs where SH2 < SH1 (descending slope)
      2. Fit a trendline through them: projected_level = SH2 + slope × (curr_idx - SH2_idx)
      3. Current bar's HIGH reaches the projected level (within 0.3% touch tolerance)
      4. Current bar CLOSES below the projected level (rejection confirmed)
      5. RVOL ≥ 1.3× on the rejection bar
      6. Price below VWAP

    Detection (ascending channel — bullish): symmetric logic on swing lows.

    Slope sanity: |slope| must exceed 0.002 per bar (filter flat/choppy channels).
    Channel age: both pivots must be within last 40 bars (fresh channel, not ancient).

    Confidence: 0.75–0.90 — highest of the secondary strategies because a clean
    trendline tag with a rejection candle is a very high-conviction entry.
    """
    if len(today) < 25:
        return None

    last_bar = today.iloc[-1]
    bar_min  = last_bar["time"].hour * 60 + last_bar["time"].minute

    # Gate 1: session window 09:45–14:00 ET
    if not (9 * 60 + 45 <= bar_min <= 14 * 60):
        return None

    rvol  = float(last_bar["rvol"])  if not pd.isna(last_bar.get("rvol",  np.nan)) else 0.0
    vwap  = float(last_bar["vwap"])  if not pd.isna(last_bar.get("vwap",  np.nan)) else None
    close = float(last_bar["close"])
    high  = float(last_bar["high"])
    low_  = float(last_bar["low"])
    curr_idx = len(today) - 1

    # Gate 2: dynamic RVOL threshold — deferred to per-direction confirmation.
    # A verified channel (descending SH pair or ascending SL pair) IS MSA
    # confirmation, so we pass msa_confirmed=True → gate drops to 0.5×.
    # This allows afternoon/slow-channel breakdowns (1:00 PM SPY/QQQ) where
    # RVOL is structurally lower but the channel setup is pristine.
    _rvol_min = _get_dynamic_rvol_threshold(
        bar_min, close, None, vwap, "CHAN_BREAK", msa_confirmed=True)

    msa   = MarketStructureAnalyzer(today)
    highs = msa._highs()
    lows  = msa._lows()

    # ── DESCENDING CHANNEL: bearish short at upper trendline ─────────────────
    if len(highs) >= 2:
        # Walk backward through swing highs to find the freshest descending pair
        for j in range(len(highs) - 1, 0, -1):
            sh2 = highs[j]       # more recent, lower
            sh1 = highs[j - 1]   # older, higher

            # Must be a descending pair
            if sh2["price"] >= sh1["price"]:
                continue

            # Both pivots must be within 40 bars (fresh channel)
            if (curr_idx - sh1["idx"]) > 40:
                break  # older than 40 bars — channel is stale, stop searching

            # Trendline slope (price change per bar index)
            slope = (sh2["price"] - sh1["price"]) / max(sh2["idx"] - sh1["idx"], 1)

            # Slope sanity — flat channels are consolidation, not a true channel
            if abs(slope) < 0.002:
                logger.debug("CHAN_BREAK: slope %.4f too flat — skipped", slope)
                continue

            # Project upper trendline to current bar
            projected = sh2["price"] + slope * (curr_idx - sh2["idx"])

            # Touch check: bar's HIGH must reach within 0.3% of the projected line
            touch_pct = (high - projected) / max(projected, 1.0)
            if not (-0.001 <= touch_pct <= 0.003):
                # Bar didn't tag the channel — not a setup
                logger.debug(
                    "CHAN_BREAK bearish: high %.2f vs projected %.2f (touch %.3f%%) — no tag",
                    high, projected, touch_pct * 100,
                )
                break  # most recent pair tried — don't go further back

            # Rejection: close must be BELOW the projected trendline
            if close >= projected:
                logger.debug(
                    "CHAN_BREAK bearish: close %.2f >= projected %.2f — no rejection", close, projected,
                )
                break

            # VWAP alignment: bearish entry requires price below VWAP
            if vwap is not None and close >= vwap:
                logger.debug("CHAN_BREAK bearish: close %.2f >= vwap %.2f", close, vwap)
                break

            # RVOL gate — checked AFTER structure confirmed so low-volume
            # legitimate channel breakdowns (1:00 PM slow bleed) still qualify.
            if rvol < _rvol_min:
                logger.debug(
                    "CHAN_BREAK bearish: RVOL %.2f < %.2f (dynamic threshold) — skipped",
                    rvol, _rvol_min,
                )
                break

            # Clean rejection at institutional supply — build confidence
            # Bigger rejection candle (high-to-close spread) = higher conviction
            rejection_body = (high - close) / max(high - low_, 0.01)   # 0→1
            channel_age    = curr_idx - sh1["idx"]                       # bars since first pivot
            recency_bonus  = max(0, 0.05 - channel_age * 0.001)          # fresher = better
            rvol_bonus     = min(0.08, max(rvol - _rvol_min, 0) * 0.07)
            body_bonus     = min(0.05, rejection_body * 0.06)
            confidence     = min(0.90, 0.75 + rvol_bonus + body_bonus + recency_bonus)

            logger.info(
                "CHAN_BREAK bearish rejection: sh1=%.2f sh2=%.2f slope=%.4f "
                "projected=%.2f high=%.2f close=%.2f RVOL=%.2f (min=%.2f) conf=%.2f",
                sh1["price"], sh2["price"], slope,
                projected, high, close, rvol, _rvol_min, confidence,
            )
            return Signal(
                strategy_id = "CHAN_BREAK",
                direction   = "bearish",
                trigger_bar = last_bar["time"],
                confidence  = confidence,
                rvol        = rvol,
                meta        = {
                    "trigger":         "descending_channel_rejection",
                    "sh1_price":       sh1["price"],
                    "sh2_price":       sh2["price"],
                    "slope_per_bar":   round(slope, 4),
                    "projected":       round(projected, 2),
                    "touch_pct":       round(touch_pct * 100, 3),
                    "rejection_body":  round(rejection_body, 2),
                    "entry_bar_high":  round(high, 4),   # structural stop: PUT exits if reclaims this
                    "rvol_gate":        round(_rvol_min, 2),
                    "rvol_gate_reason": _rvol_threshold_reason(
                        bar_min, close, None, vwap, "CHAN_BREAK", msa_confirmed=True),
                },
            )

    # ── ASCENDING CHANNEL: bullish long at lower trendline ───────────────────
    if len(lows) >= 2:
        for j in range(len(lows) - 1, 0, -1):
            sl2 = lows[j]        # more recent, higher
            sl1 = lows[j - 1]    # older, lower

            if sl2["price"] <= sl1["price"]:
                continue

            if (curr_idx - sl1["idx"]) > 40:
                break

            slope = (sl2["price"] - sl1["price"]) / max(sl2["idx"] - sl1["idx"], 1)

            if abs(slope) < 0.002:
                logger.debug("CHAN_BREAK ascending: slope %.4f too flat — skipped", slope)
                continue

            projected = sl2["price"] + slope * (curr_idx - sl2["idx"])

            # Touch: bar's LOW must tag within 0.3% of projected lower trendline
            touch_pct = (projected - low_) / max(projected, 1.0)
            if not (-0.001 <= touch_pct <= 0.003):
                logger.debug(
                    "CHAN_BREAK bullish: low %.2f vs projected %.2f (touch %.3f%%) — no tag",
                    low_, projected, touch_pct * 100,
                )
                break

            # Bounce: close must be ABOVE the projected trendline
            if close <= projected:
                logger.debug(
                    "CHAN_BREAK bullish: close %.2f <= projected %.2f — no bounce", close, projected,
                )
                break

            # VWAP alignment: bullish entry requires price above VWAP
            if vwap is not None and close <= vwap:
                logger.debug("CHAN_BREAK bullish: close %.2f <= vwap %.2f", close, vwap)
                break

            # MSA trend alignment: block bullish channel bounces in confirmed downtrends.
            # Ascending-channel bounces inside a LH/LL sequence are counter-trend fades —
            # the relief bounce is the institution's next sell point, not a buy.
            _cb_trend = MarketStructureAnalyzer(today).classify_trend()
            if _cb_trend == "downtrend":
                logger.debug(
                    "CHAN_BREAK bullish: MSA classify_trend=%s — blocked (counter-trend)",
                    _cb_trend,
                )
                break

            # RVOL gate — deferred until structure is confirmed
            if rvol < _rvol_min:
                logger.debug(
                    "CHAN_BREAK bullish: RVOL %.2f < %.2f (dynamic threshold) — skipped",
                    rvol, _rvol_min,
                )
                break

            # Bounce body: close-to-low spread relative to bar range
            bounce_body   = (close - low_) / max(high - low_, 0.01)
            channel_age   = curr_idx - sl1["idx"]
            recency_bonus = max(0, 0.05 - channel_age * 0.001)
            rvol_bonus    = min(0.08, max(rvol - _rvol_min, 0) * 0.07)
            body_bonus    = min(0.05, bounce_body * 0.06)
            confidence    = min(0.90, 0.75 + rvol_bonus + body_bonus + recency_bonus)

            logger.info(
                "CHAN_BREAK bullish bounce: sl1=%.2f sl2=%.2f slope=%.4f "
                "projected=%.2f low=%.2f close=%.2f RVOL=%.2f (min=%.2f) conf=%.2f",
                sl1["price"], sl2["price"], slope,
                projected, low_, close, rvol, _rvol_min, confidence,
            )
            return Signal(
                strategy_id = "CHAN_BREAK",
                direction   = "bullish",
                trigger_bar = last_bar["time"],
                confidence  = confidence,
                rvol        = rvol,
                meta        = {
                    "trigger":        "ascending_channel_bounce",
                    "sl1_price":      sl1["price"],
                    "sl2_price":      sl2["price"],
                    "slope_per_bar":  round(slope, 4),
                    "projected":      round(projected, 2),
                    "touch_pct":      round(touch_pct * 100, 3),
                    "bounce_body":    round(bounce_body, 2),
                    "entry_bar_low":  round(low_, 4),   # structural stop reference for CALL
                    "rvol_gate":        round(_rvol_min, 2),
                    "rvol_gate_reason": _rvol_threshold_reason(
                        bar_min, close, None, vwap, "CHAN_BREAK", msa_confirmed=True),
                },
            )

    return None


# ═══════════════════════════════════════════════════════════════════════════════
# Public router — called once per tick from trading_logic._tick()
# ═══════════════════════════════════════════════════════════════════════════════

def route_signals(
    df: pd.DataFrame,
    ticker: str,
    enabled_strategies: set[str] | None = None,
) -> list[Signal]:
    """
    Evaluate all strategy modules against the current bar data and return
    a list of qualifying signals sorted by confidence (highest first).

    Strategy IDs (eight total):
      INST_ORB   — Morning ORB breakout  (09:30–10:30, vol_sma20×2.0, MSA guard)
      BOS_MSS    — Break of Structure / Market Structure Shift
      VWAP_PB    — VWAP Pullback (trend continuation)
      FVG        — Fair Value Gap (imbalance retest)
      MID_BRK    — Mid-Day Breakdown  (10:30–13:00, LH confirmed, bearish)
      AFT_REV    — Afternoon Reversal (13:00–15:30, HL + SH breakout, bullish)
      TREND_CONT — Trend Continuation re-entry at LH (bearish) / HL (bullish)
      CHAN_BREAK  — Channel trendline rejection (descending/ascending)

    The caller (trading_logic._tick) should:
      1. Take signals[0] if the list is non-empty
      2. Log Signal.strategy_id as Strategy_ID in the trade_opened event
      3. Pass Signal.rvol as Entry_Volume_Multiplier to the audit log

    Args:
        df                  : Multi-day 5-min OHLCV DataFrame (today's session +
                              prior days for RVOL calculation).
        ticker              : Symbol string (used only for log messages).
        enabled_strategies  : Optional set of strategy IDs to evaluate.
                              If None (default), all eight strategies run.
                              Pass e.g. {"INST_ORB", "MID_BRK"} to restrict.

    Returns:
        Sorted list[Signal] (may be empty if no strategy qualifies).
    """
    if df.empty or len(df) < 2:
        return []

    # Kill-lock guard — if risk.py has frozen trading (daily loss cap or manual
    # trigger), skip all evaluators immediately.  This is the earliest possible
    # gate so no CPU is spent generating signals that trading_logic would discard.
    _killed, _kill_reason = check_kill_lock()
    if _killed:
        logger.warning(
            "route_signals blocked by kill lock",
            extra={"event": "kill_lock_blocked", "reason": _kill_reason, "ticker": ticker},
        )
        return []

    # Build indicator frame once; all strategies share it
    today = _build_indicator_frame(df)
    if today.empty:
        return []

    signals: list[Signal] = []

    # Full evaluator table — session-window functions self-gate on bar time,
    # so all eight can be called every tick safely.
    _all_evaluators = [
        ("INST_ORB",   _eval_inst_orb),
        ("BOS_MSS",    _eval_bos_mss),
        ("VWAP_PB",    _eval_vwap_pullback),
        ("FVG",        _eval_fvg),
        ("MID_BRK",    _eval_midday_breakdown),
        ("AFT_REV",    _eval_afternoon_reversal),
        ("TREND_CONT", _eval_trend_cont),
        ("CHAN_BREAK",  _eval_chan_break),
    ]
    evaluators = (
        [(sid, fn) for sid, fn in _all_evaluators if sid in enabled_strategies]
        if enabled_strategies is not None
        else _all_evaluators
    )

    for strategy_id, fn in evaluators:
        try:
            sig = fn(today)
            if sig is not None:
                signals.append(sig)
                logger.info(
                    "strategy_signal",
                    extra={
                        "event":       "strategy_signal",
                        "strategy_id": strategy_id,
                        "ticker":      ticker,
                        "direction":   sig.direction,
                        "confidence":  round(sig.confidence, 3),
                        "rvol":        round(sig.rvol, 2),
                    },
                )
        except Exception as exc:
            logger.warning("Strategy %s raised: %s", strategy_id, exc, exc_info=True)

    # Sort highest confidence first
    signals.sort(key=lambda s: s.confidence, reverse=True)

    if signals:
        logger.info(
            "router_result: %d signal(s) for %s — top=%s %.0f%% conf",
            len(signals), ticker,
            signals[0].strategy_id,
            signals[0].confidence * 100,
        )

    # ── Plain-English audit log — structural state + signal decisions ─────────
    # Writes to system_events only when the market structure changes so we don't
    # flood the DB.  'SIM' ticker is excluded to keep the live log clean.
    try:
        if ticker != "SIM":
            _audit_plain_english(today, ticker, signals)
    except Exception:
        pass   # never let audit logging crash the router

    return signals


# ── Plain-English Audit Helper ────────────────────────────────────────────────

_STRAT_NAMES = {
    "INST_ORB":   "Opening Range Breakout",
    "BOS_MSS":    "Break of Structure",
    "VWAP_PB":    "VWAP Pullback",
    "FVG":        "Fair Value Gap",
    "MID_BRK":    "Mid-Day Breakdown",
    "AFT_REV":    "Afternoon Reversal",
    "TREND_CONT": "Trend Continuation",
    "CHAN_BREAK":  "Channel Rejection",
}

_RVOL_NEEDED = {
    "INST_ORB": 2.0, "BOS_MSS": 1.5, "VWAP_PB": 1.5,
    "FVG": 1.5, "MID_BRK": 1.0, "AFT_REV": 1.2,
    "TREND_CONT": 1.2, "CHAN_BREAK": 1.3,
}


def _audit_plain_english(today: pd.DataFrame, ticker: str, signals: list) -> None:
    """
    Write plain-English structural and decision events to system_events.
    Fires only when the market structure (trend / swing pivots) changes
    relative to the last logged state — prevents DB spam on quiet ticks.
    """
    global _last_audit_state

    if len(today) < 10:
        return

    last_bar  = today.iloc[-1]
    bar_time  = last_bar["time"]
    bar_str   = bar_time.strftime("%H:%M") if hasattr(bar_time, "strftime") else str(bar_time)
    rvol_now  = float(last_bar.get("rvol", 0) or 0)
    close_now = float(last_bar["close"])
    vwap_now  = float(last_bar.get("vwap", close_now) or close_now)

    msa      = MarketStructureAnalyzer(today)
    trend    = msa.classify_trend()
    highs    = msa._highs()
    lows     = msa._lows()
    last_sh  = highs[-1]["price"] if highs else None
    last_sl  = lows[-1]["price"]  if lows  else None

    state_key = f"{ticker}:{trend}:{last_sh}:{last_sl}"
    prev_key  = _last_audit_state.get("key", "")

    # ── 1. Structural change event ────────────────────────────────────────────
    if state_key != prev_key:
        _last_audit_state["key"] = state_key

        # Describe the trend in plain English
        if trend == "downtrend":
            # Check if newest high is a Lower High
            is_lh = (len(highs) >= 2 and highs[-1]["price"] < highs[-2]["price"])
            is_ll = (len(lows)  >= 2 and lows[-1]["price"]  < lows[-2]["price"])
            if is_lh and is_ll:
                struct_msg = (
                    f"{ticker} {bar_str} — Bearish structure confirmed. "
                    f"Price just made a Lower High at ${last_sh:.2f} (couldn't reclaim prior peak) "
                    f"and a Lower Low at ${last_sl:.2f}. This is a downtrend — bot is looking for SHORT/PUT entries."
                )
            elif is_lh:
                struct_msg = (
                    f"{ticker} {bar_str} — Lower High printed at ${last_sh:.2f}. "
                    f"Rally failed below the prior swing high — sellers still in control. "
                    f"Waiting for a Lower Low to confirm full downtrend."
                )
            else:
                struct_msg = (
                    f"{ticker} {bar_str} — Downtrend in progress. "
                    f"Last swing high ${last_sh:.2f}, last swing low ${last_sl:.2f}. "
                    f"Price at ${close_now:.2f}, {'below' if close_now < vwap_now else 'above'} VWAP."
                )
        elif trend == "uptrend":
            is_hh = (len(highs) >= 2 and highs[-1]["price"] > highs[-2]["price"])
            is_hl = (len(lows)  >= 2 and lows[-1]["price"]  > lows[-2]["price"])
            if is_hh and is_hl:
                struct_msg = (
                    f"{ticker} {bar_str} — Bullish structure confirmed. "
                    f"Higher High at ${last_sh:.2f} and Higher Low at ${last_sl:.2f}. "
                    f"This is an uptrend — bot is looking for LONG/CALL entries."
                )
            elif is_hl:
                struct_msg = (
                    f"{ticker} {bar_str} — Higher Low at ${last_sl:.2f}. "
                    f"Pullback held above prior swing low — buyers defending. "
                    f"Waiting for a Higher High to confirm full uptrend."
                )
            else:
                struct_msg = (
                    f"{ticker} {bar_str} — Uptrend in progress. "
                    f"Last swing high ${last_sh:.2f}, last swing low ${last_sl:.2f}."
                )
        else:
            struct_msg = (
                f"{ticker} {bar_str} — Consolidating. No clear trend yet "
                f"(price swinging between ${last_sl:.2f if last_sl else 0:.2f} and "
                f"${last_sh:.2f if last_sh else 0:.2f}). Bot is waiting for a breakout."
            )

        _db_log("INFO", "structure", struct_msg)

    # ── 2. RVOL advisory (log once per RVOL tier change) ─────────────────────
    prev_rvol_tier = _last_audit_state.get("rvol_tier", "")
    cur_rvol_tier  = ("≥2.0" if rvol_now >= 2.0 else "≥1.5" if rvol_now >= 1.5
                      else "≥1.2" if rvol_now >= 1.2 else "<1.2")
    if cur_rvol_tier != prev_rvol_tier:
        _last_audit_state["rvol_tier"] = cur_rvol_tier
        if rvol_now >= 2.0:
            rvol_msg = (
                f"{ticker} {bar_str} — Volume is {rvol_now:.1f}× above average. "
                f"All 8 strategies are now volume-eligible. Institutional activity detected."
            )
        elif rvol_now >= 1.5:
            rvol_msg = (
                f"{ticker} {bar_str} — Volume at {rvol_now:.1f}× average. "
                f"BOS, VWAP Pullback, FVG eligible. Institutional ORB still needs 2.0×."
            )
        elif rvol_now >= 1.2:
            rvol_msg = (
                f"{ticker} {bar_str} — Volume at {rvol_now:.1f}× average. "
                f"Only Trend Continuation and Channel Rejection eligible. Waiting for volume."
            )
        else:
            rvol_msg = (
                f"{ticker} {bar_str} — Volume low ({rvol_now:.1f}× average). "
                f"No strategies eligible. Bot is watching but will not enter."
            )
        _db_log("INFO", "volume", rvol_msg)

    # ── 3. Signal fired — rich plain-English entry explanation ────────────────
    if signals:
        top = signals[0]
        name    = _STRAT_NAMES.get(top.strategy_id, top.strategy_id)
        dir_txt = "PUT (short)" if top.direction == "bearish" else "CALL (long)"
        meta    = top.meta or {}

        if top.strategy_id == "INST_ORB":
            entry_msg = (
                f"{ticker} {bar_str} — ENTRY SIGNAL: {name}. "
                f"Price broke {'above' if top.direction == 'bullish' else 'below'} the opening range "
                f"with {top.rvol:.1f}× volume. VWAP aligned. Entering {dir_txt}."
            )
        elif top.strategy_id == "BOS_MSS":
            entry_msg = (
                f"{ticker} {bar_str} — ENTRY SIGNAL: {name}. "
                f"Price broke through a prior swing {'high' if top.direction == 'bullish' else 'low'}, "
                f"confirming a market structure shift. Volume {top.rvol:.1f}×. Entering {dir_txt}."
            )
        elif top.strategy_id == "TREND_CONT":
            lh_p = meta.get("lh_price") or meta.get("hl_price", close_now)
            entry_msg = (
                f"{ticker} {bar_str} — ENTRY SIGNAL: {name} (re-entry). "
                f"{'Lower High' if top.direction == 'bearish' else 'Higher Low'} at ${lh_p:.2f} failed "
                f"to break the prior peak — trend resuming. Volume {top.rvol:.1f}×. Entering {dir_txt}."
            )
        elif top.strategy_id == "CHAN_BREAK":
            proj = meta.get("projected", close_now)
            entry_msg = (
                f"{ticker} {bar_str} — ENTRY SIGNAL: {name}. "
                f"Price tagged the {'descending' if top.direction == 'bearish' else 'ascending'} channel "
                f"trendline at ~${proj:.2f} and rejected. Volume {top.rvol:.1f}×. Entering {dir_txt}."
            )
        elif top.strategy_id == "VWAP_PB":
            entry_msg = (
                f"{ticker} {bar_str} — ENTRY SIGNAL: {name}. "
                f"Price pulled back to VWAP (${vwap_now:.2f}) and is resuming the "
                f"{'uptrend' if top.direction == 'bullish' else 'downtrend'}. Volume {top.rvol:.1f}×. Entering {dir_txt}."
            )
        elif top.strategy_id == "MID_BRK":
            entry_msg = (
                f"{ticker} {bar_str} — ENTRY SIGNAL: {name}. "
                f"Price collapsed below the opening range and VWAP with a confirmed Lower High "
                f"already on the chart. Volume {top.rvol:.1f}×. Mid-day breakdown — entering {dir_txt}."
            )
        elif top.strategy_id == "AFT_REV":
            entry_msg = (
                f"{ticker} {bar_str} — ENTRY SIGNAL: {name}. "
                f"After a downtrend, price printed a Higher Low and broke above a prior swing high. "
                f"Volume {top.rvol:.1f}×. Afternoon reversal — entering {dir_txt}."
            )
        else:
            entry_msg = (
                f"{ticker} {bar_str} — ENTRY SIGNAL: {name} {dir_txt}. "
                f"Volume {top.rvol:.1f}×, confidence {top.confidence:.0%}."
            )
        _db_log("INFO", "signal", entry_msg)

    # ── 4. No signal — explain the top blocking reason ────────────────────────
    elif state_key != prev_key:   # only log skip reason on structural change
        # Diagnose the most likely blocking reason
        if rvol_now < 1.2:
            skip_msg = (
                f"{ticker} {bar_str} — No entry. Volume too low ({rvol_now:.1f}× average, "
                f"need at least 1.2× for any strategy). Bot is watching the tape."
            )
        elif trend == "consolidation":
            skip_msg = (
                f"{ticker} {bar_str} — No entry. Price is ranging with no clear direction. "
                f"Bot needs a confirmed uptrend or downtrend before entering."
            )
        elif rvol_now < 2.0 and trend in ("uptrend", "downtrend"):
            needed = "Opening Range Breakout" if rvol_now < 2.0 else ""
            skip_msg = (
                f"{ticker} {bar_str} — Trend is {'bullish' if trend == 'uptrend' else 'bearish'} "
                f"but volume only {rvol_now:.1f}× (need 2.0× for ORB, 1.5× for BOS/VWAP). "
                f"Watching for volume surge."
            )
        else:
            vwap_side = "above" if close_now > vwap_now else "below"
            skip_msg = (
                f"{ticker} {bar_str} — Trend: {trend}. Price ${close_now:.2f} ({vwap_side} VWAP). "
                f"Volume {rvol_now:.1f}×. No pattern triggered this bar — continuing to monitor."
            )
        _db_log("INFO", "scan", skip_msg)

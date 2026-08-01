"""
strategy_audit_log.py — Plain-English structural/decision audit logger.

Extracted from strategy_router.py (2026-07-16) to keep the router itself
under ~200 lines. Writes human-readable narration to system_events so the
dashboard can show WHY the bot did or didn't take a trade, without needing
to read raw signal/confidence numbers. Fires only on structural change or
RVOL-tier change to avoid spamming the DB every single bar.
"""

from __future__ import annotations

import pandas as pd

from database import log_event as _db_log
from strategies.base import MarketStructureAnalyzer

_STRAT_NAMES = {
    "INST_ORB":   "Opening Range Breakout",
    "BOS_MSS":    "Break of Structure",
    "VWAP_PB":    "VWAP Pullback",
    "FVG":        "Fair Value Gap",
    "IFVG":       "Inverted Fair Value Gap",
    "MID_BRK":    "Mid-Day Breakdown",
    "AFT_REV":    "Afternoon Reversal",
    "TREND_CONT": "Trend Continuation",
    "CHAN_BREAK":  "Channel Rejection",
}

# Tracks last-logged structure so we don't spam the DB with duplicate events
_last_audit_state: dict = {}


def audit_plain_english(today: pd.DataFrame, ticker: str, signals: list) -> None:
    """
    Write plain-English structural and decision events to system_events.
    Fires only when market structure changes to avoid DB spam.
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

    msa     = MarketStructureAnalyzer(today)
    trend   = msa.classify_trend()
    highs   = msa._highs()
    lows    = msa._lows()
    last_sh = highs[-1]["price"] if highs else None
    last_sl = lows[-1]["price"]  if lows  else None

    state_key = f"{ticker}:{trend}:{last_sh}:{last_sl}"
    prev_key  = _last_audit_state.get("key", "")

    # ── 1. Structural change event ────────────────────────────────────────────
    if state_key != prev_key:
        _last_audit_state["key"] = state_key

        if trend == "downtrend":
            is_lh = len(highs) >= 2 and highs[-1]["price"] < highs[-2]["price"]
            is_ll = len(lows)  >= 2 and lows[-1]["price"]  < lows[-2]["price"]
            if is_lh and is_ll:
                struct_msg = (
                    f"{ticker} {bar_str} — Bearish structure confirmed. "
                    f"Lower High ${last_sh:.2f} + Lower Low ${last_sl:.2f}. "
                    f"Bot looking for SHORT/PUT entries."
                )
            elif is_lh:
                struct_msg = (
                    f"{ticker} {bar_str} — Lower High at ${last_sh:.2f}. "
                    f"Rally failed below prior peak — sellers in control. Waiting for LL confirmation."
                )
            else:
                struct_msg = (
                    f"{ticker} {bar_str} — Downtrend in progress. "
                    f"Last SH ${last_sh:.2f}, last SL ${last_sl:.2f}. "
                    f"Price ${close_now:.2f} {'below' if close_now < vwap_now else 'above'} VWAP."
                )
        elif trend == "uptrend":
            is_hh = len(highs) >= 2 and highs[-1]["price"] > highs[-2]["price"]
            is_hl = len(lows)  >= 2 and lows[-1]["price"]  > lows[-2]["price"]
            if is_hh and is_hl:
                struct_msg = (
                    f"{ticker} {bar_str} — Bullish structure confirmed. "
                    f"Higher High ${last_sh:.2f} + Higher Low ${last_sl:.2f}. "
                    f"Bot looking for LONG/CALL entries."
                )
            elif is_hl:
                struct_msg = (
                    f"{ticker} {bar_str} — Higher Low at ${last_sl:.2f}. "
                    f"Pullback held above prior low — buyers defending. Waiting for HH."
                )
            else:
                struct_msg = (
                    f"{ticker} {bar_str} — Uptrend in progress. "
                    f"Last SH ${last_sh:.2f}, last SL ${last_sl:.2f}."
                )
        else:
            struct_msg = (
                f"{ticker} {bar_str} — Consolidating. No clear trend. "
                f"Bot waiting for breakout."
            )

        _db_log("INFO", "structure", struct_msg)

    # ── 2. RVOL advisory (log once per tier change) ───────────────────────────
    prev_rvol_tier = _last_audit_state.get("rvol_tier", "")
    cur_rvol_tier  = ("≥2.0" if rvol_now >= 2.0 else "≥1.5" if rvol_now >= 1.5
                      else "≥1.2" if rvol_now >= 1.2 else "<1.2")
    if cur_rvol_tier != prev_rvol_tier:
        _last_audit_state["rvol_tier"] = cur_rvol_tier
        if rvol_now >= 2.0:
            rvol_msg = f"{ticker} {bar_str} — Volume {rvol_now:.1f}× average. All strategies eligible."
        elif rvol_now >= 1.5:
            rvol_msg = (
                f"{ticker} {bar_str} — Volume {rvol_now:.1f}×. "
                f"BOS/VWAP/FVG eligible. ORB needs 2.0×."
            )
        elif rvol_now >= 1.2:
            rvol_msg = (
                f"{ticker} {bar_str} — Volume {rvol_now:.1f}×. "
                f"Only TREND_CONT + CHAN_BREAK eligible. Waiting for volume."
            )
        else:
            rvol_msg = (
                f"{ticker} {bar_str} — Volume low ({rvol_now:.1f}×). "
                f"No strategies eligible. Watching."
            )
        _db_log("INFO", "volume", rvol_msg)

    # ── 3. Signal fired ───────────────────────────────────────────────────────
    if signals:
        top     = signals[0]
        name    = _STRAT_NAMES.get(top.strategy_id, top.strategy_id)
        dir_txt = "PUT (short)" if top.direction == "bearish" else "CALL (long)"
        meta    = top.meta or {}

        if top.strategy_id == "INST_ORB":
            flipped = meta.get("direction_flipped", False)
            entry_msg = (
                f"{ticker} {bar_str} — ENTRY: {name}{'  [failed-breakout fade]' if flipped else ''}. "
                f"Price broke {'above' if top.direction == 'bullish' else 'below'} the opening range "
                f"with {top.rvol:.1f}× volume. Entering {dir_txt}."
            )
        elif top.strategy_id == "BOS_MSS":
            entry_msg = (
                f"{ticker} {bar_str} — ENTRY: {name}. "
                f"Broke prior swing {'high' if top.direction == 'bullish' else 'low'}. "
                f"Volume {top.rvol:.1f}×. Entering {dir_txt}."
            )
        elif top.strategy_id == "TREND_CONT":
            lh_p = meta.get("lh_price") or meta.get("hl_price", close_now)
            entry_msg = (
                f"{ticker} {bar_str} — ENTRY: {name} (re-entry). "
                f"{'LH' if top.direction == 'bearish' else 'HL'} at ${lh_p:.2f} — "
                f"trend resuming. Volume {top.rvol:.1f}×. Entering {dir_txt}."
            )
        elif top.strategy_id == "CHAN_BREAK":
            proj = meta.get("projected", close_now)
            entry_msg = (
                f"{ticker} {bar_str} — ENTRY: {name}. "
                f"Trendline tag at ~${proj:.2f}, rejection confirmed. "
                f"Volume {top.rvol:.1f}×. Entering {dir_txt}."
            )
        else:
            entry_msg = (
                f"{ticker} {bar_str} — ENTRY: {name} {dir_txt}. "
                f"Volume {top.rvol:.1f}×, conf {top.confidence:.0%}."
            )
        _db_log("INFO", "signal", entry_msg)

    # ── 4. No signal — log blocking reason on structural change ───────────────
    elif state_key != prev_key:
        if rvol_now < 1.2:
            skip_msg = (
                f"{ticker} {bar_str} — No entry. Volume {rvol_now:.1f}× "
                f"(need ≥1.2× for any strategy). Watching."
            )
        elif trend == "consolidation":
            skip_msg = (
                f"{ticker} {bar_str} — No entry. Ranging — no confirmed trend. "
                f"Bot waiting for breakout."
            )
        else:
            vwap_side = "above" if close_now > vwap_now else "below"
            skip_msg = (
                f"{ticker} {bar_str} — Trend: {trend}. "
                f"Price ${close_now:.2f} ({vwap_side} VWAP). "
                f"Volume {rvol_now:.1f}×. No pattern triggered — monitoring."
            )
        _db_log("INFO", "scan", skip_msg)

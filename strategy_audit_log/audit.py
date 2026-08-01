"""
strategy_audit_log/audit.py — audit_plain_english(): the orchestrator that
decides WHEN to fire each of the 4 narration sections and writes them to
system_events via database.log_event.

Split out of the old single strategy_audit_log.py (2026-08-01, file-size
cleanup). The message-building logic itself lives in messages.py; this file
keeps the original function's control flow (dedup checks, variable
extraction, _db_log calls) unchanged.
"""
from __future__ import annotations

import pandas as pd

from database import log_event as _db_log
from strategies.base import MarketStructureAnalyzer

from strategy_audit_log.state import _last_audit_state
from strategy_audit_log.messages import (
    build_structure_message,
    build_rvol_message,
    build_entry_message,
    build_skip_message,
)


def audit_plain_english(today: pd.DataFrame, ticker: str, signals: list) -> None:
    """
    Write plain-English structural and decision events to system_events.
    Fires only when market structure changes to avoid DB spam.
    """
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
        struct_msg = build_structure_message(
            ticker, bar_str, trend, highs, lows, last_sh, last_sl, close_now, vwap_now,
        )
        _db_log("INFO", "structure", struct_msg)

    # ── 2. RVOL advisory (log once per tier change) ───────────────────────────
    prev_rvol_tier = _last_audit_state.get("rvol_tier", "")
    cur_rvol_tier, rvol_msg = build_rvol_message(ticker, bar_str, rvol_now)
    if cur_rvol_tier != prev_rvol_tier:
        _last_audit_state["rvol_tier"] = cur_rvol_tier
        _db_log("INFO", "volume", rvol_msg)

    # ── 3. Signal fired ───────────────────────────────────────────────────────
    if signals:
        top = signals[0]
        entry_msg = build_entry_message(ticker, bar_str, close_now, top)
        _db_log("INFO", "signal", entry_msg)

    # ── 4. No signal — log blocking reason on structural change ───────────────
    elif state_key != prev_key:
        skip_msg = build_skip_message(ticker, bar_str, rvol_now, trend, close_now, vwap_now)
        _db_log("INFO", "scan", skip_msg)

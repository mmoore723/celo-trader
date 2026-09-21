"""
trading/diagnostics/bar_thinking.py — _log_bar_thinking: emits one
human-readable "Thinking" panel audit-log entry per 1-min bar, narrating
what the bot is watching and why it is/isn't acting.

Split out of the old single trading/diagnostics.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.

Kept as ONE function rather than split further: it's a single narrative
builder walking through one bar's full context (regime, RVOL, MTF bias,
per-strategy gate state, etc.) to construct one coherent audit-log message
-- splitting it would fragment the narrative logic without a natural
functional seam, the same reasoning behind every other "irreducible
sequential function" kept whole in this refactor.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from trading.state import get_user_state, get_user_risk, _now_et, _default_user_id

logger = logging.getLogger("celo_trader.trading_logic")

def _log_bar_thinking(df1m: "pd.DataFrame", df5: "pd.DataFrame", ticker: str) -> None:
    """
    Emit one detailed human-readable audit log entry per newly closed 1-min candle.

    Two modes:
      • IN TRADE  — narrates live position: P&L, stop distance, Stage 1 target,
                    time-box countdown, momentum check.
      • SCANNING  — gate-by-gate ORB checklist: price vs. OR levels, RVOL, VWAP,
                    what's passing, what's missing, what happens next.

    df1m — today's 1-min bars (timing, current price)
    df5  — augmented multi-day 5-min bars (RVOL baseline, ORB range)
    """
    try:
        if df1m is None or df1m.empty:
            return

        _US = get_user_state()
        import pandas as _pd
        from signals import (
            get_opening_range  as _get_or,
            compute_vwap       as _cvwap,
            compute_rvol       as _crvol,
            ORB_RVOL_THRESHOLD as _ORB_RVOL,
        )
        from database import log_event

        # ── Isolate today's 1-min bars ────────────────────────────────────────
        latest_date = df1m["time"].dt.date.max()
        today_1m    = df1m[df1m["time"].dt.date == latest_date].reset_index(drop=True)
        if len(today_1m) < 2:
            return

        last_bar     = today_1m.iloc[-1]
        bar_time_str = str(last_bar["time"])

        # Guard: already emitted this exact 1-min bar FOR THIS TICKER.
        # Per-ticker key so NVDA and SPY each get one log per bar close, even
        # when both are in the watchlist and processed on the same tick cycle.
        _guard_key = f"last_1m_bar_time_{ticker}"
        if _US.get(_guard_key) == bar_time_str:
            return
        _US[_guard_key] = bar_time_str

        close = float(last_bar["close"])
        bar_t = bar_time_str[11:16]   # "HH:MM"

        # ── 5-min today slice (ORB detection uses 5-min bars) ─────────────────
        latest_date_5m = df5["time"].dt.date.max()
        # BUG FIX 2026-07-22: capture today's row labels BEFORE reset_index.
        # rvol_series below is indexed on the full multi-day df5; reindexing
        # against today_df.index AFTER it's reset to 0..N-1 silently pulls
        # whichever earlier day starts at the same row offset instead of
        # today's real RVOL. Same bug, same fix as strategy_router.py's
        # _build_indicator_frame() (fixed earlier today).
        today_idx      = df5.index[df5["time"].dt.date == latest_date_5m]
        today_df       = df5[df5["time"].dt.date == latest_date_5m].reset_index(drop=True)

        # ── VWAP (on today's 1-min bars for precision) ─────────────────────────
        try:
            vwap_series = _cvwap(today_1m)
            vwap_val    = float(vwap_series.iloc[-1]) if not _pd.isna(vwap_series.iloc[-1]) else None
        except Exception:
            vwap_val = None

        # ── RVOL (augmented df gives 10-day baseline) ─────────────────────────
        try:
            rvol_series = _crvol(df5, lookback_days=10)
            rvol_today  = rvol_series.reindex(today_idx)   # reindex against PRE-reset labels
            rvol_val    = float(rvol_today.iloc[-1]) if (not rvol_today.empty and not _pd.isna(rvol_today.iloc[-1])) else 0.0
        except Exception:
            rvol_val = 0.0

        # ── Opening Range ─────────────────────────────────────────────────────
        or_info = _get_or(today_df)

        # ─────────────────────────────────────────────────────────────────────
        # BRANCH A: IN A TRADE on this ticker — narrate the live position
        # ─────────────────────────────────────────────────────────────────────
        _all_open = _US.get("open_trades") or []
        _ticker_trade = next(
            (t for t in _all_open
             if t.get("ticker") == ticker
             and t.get("strategy_id") != "RECOVERED_UNTRACKED"),
            None,
        )

        if _ticker_trade:
            _tid         = _ticker_trade.get("id")
            _pos_state   = _US.get("positions", {}).get(_tid, {})
            _entry_px    = float(_ticker_trade.get("entry_price") or 0)
            _opt_type    = (_ticker_trade.get("option_type") or "call").upper()
            _n_contracts = int(_ticker_trade.get("contracts") or 1)
            _strategy    = _ticker_trade.get("strategy_id", "UNKNOWN")
            _stage1_done = _pos_state.get("stage1_done", _US.get("stage1_done", False))
            _stop_pct    = float(_pos_state.get("current_stop_pct") or 0.20)

            # Option price — use the last-known value from per-position state
            _cur_opt = float(
                _pos_state.get("current_option_price")
                or _US.get("current_option_price")
                or _entry_px
            )
            _pnl_pct  = ((_cur_opt - _entry_px) / _entry_px * 100) if _entry_px > 0 else 0.0
            _pnl_usd  = (_cur_opt - _entry_px) * _n_contracts * 100
            _sign     = "+" if _pnl_usd >= 0 else ""
            _pnl_emoji = "🟢" if _pnl_usd >= 0 else "🔴"

            # Reviewed timers/structure bypass the generic stop/stage engine.
            # Do not describe calculated reference levels as active protection.
            from trading.diagnostics.exit_policy import reviewed_exit_description
            _reviewed_description = reviewed_exit_description(_ticker_trade, _pos_state, _now_et())
            if _reviewed_description is not None:
                log_event(
                    "INFO", "bar_eval",
                    f"{_pnl_emoji} [{ticker}] {bar_t} POSITION LIVE | "
                    f"{_opt_type} @ ${_entry_px:.2f} x {_n_contracts}ct ({_strategy}) | "
                    f"Stock ${close:.2f} | Option ${_cur_opt:.2f} | "
                    f"P&L {_pnl_pct:+.1f}% (${_pnl_usd:+.2f}) | {_reviewed_description}",
                )
                return

            # Stop levels
            _stop_px      = round(_entry_px * (1.0 - _stop_pct), 2)
            _cushion      = round(_cur_opt - _stop_px, 2)
            _pct_to_stop  = round((_cur_opt - _stop_px) / _cur_opt * 100, 1) if _cur_opt > 0 else 0

            # Stage 1 target (100% gain at 1×R)
            _s1_tgt = round(_entry_px * 1.50, 2)    # default 50% gain
            try:
                _ar = get_user_risk()
                if _ar:
                    _s1_tgt = round(_ar.stage1_exit_price(_entry_px), 2)
            except Exception:
                pass
            _s1_dist = round(_s1_tgt - _cur_opt, 2)

            # Structural stop if set
            _struct_stop = _pos_state.get("struct_stop_price")
            _struct_note = f" | Structural stop ${_struct_stop:.2f}" if _struct_stop else ""

            # Time-box countdown
            _entry_time_str = str(_ticker_trade.get("entry_time", ""))
            _time_used = 0
            try:
                _et_now_tb = _now_et()
                _entry_ts  = _pd.Timestamp(_entry_time_str)
                _entry_naive = _entry_ts.tz_localize(None) if _entry_ts.tzinfo else _entry_ts.replace(tzinfo=None)
                _now_naive   = _et_now_tb.replace(tzinfo=None)
                _time_used   = max(0, int((_now_naive - _entry_naive).total_seconds() / 60))
            except Exception:
                pass
            _timebox   = 90 if _stage1_done else 45
            _time_left = max(0, _timebox - _time_used)
            _time_pressure = " ⚠️ EXIT SOON" if _time_left <= 5 else ""

            # Stage status
            if _stage1_done:
                _stage_note = "Stage 1 HIT ✅ — running runners to Stage 2 target"
            elif _s1_dist <= 0:
                _stage_note = f"Stage 1 target ${_s1_tgt:.2f} — REACHED 🎯"
            else:
                _stage_note = (
                    f"Stage 1 target ${_s1_tgt:.2f} — "
                    f"need ${abs(_s1_dist):.2f} more ({'+' if _s1_dist < 0 else ''}{abs(round(_s1_dist/_entry_px*100,1))}%)"
                )

            # Momentum
            _mom = (
                f"RVOL {rvol_val:.1f}× — {'momentum holding 💪' if rvol_val >= 1.2 else 'volume fading ⚠️ watch for reversal'}"
            )

            # Strategy name
            _sname = {
                "V2_ORB_PULLBACK": "TSLA Opening-Range Pullback",
                "V2_SPY_TREND_CONT": "SPY Trend Continuation",
                "V2_SPY_AFTERNOON_FVG": "SPY Afternoon Fair Value Gap",
                "V2_FAILED_OR_BREAK_VWAP_REVERSION": "SPY Failed-Range Recovery",
                "V2_TSLA_TWO_LEG_TREND_PULLBACK": "TSLA Two-Leg Trend Pullback",
            }.get(_strategy, _strategy)

            # Throttle: once per minute per position
            _last_min = _pos_state.get("last_position_narration_minute")
            if _last_min == bar_t:
                return
            if _tid and _tid in _US.get("positions", {}):
                _US["positions"][_tid]["last_position_narration_minute"] = bar_t

            # Position zone descriptor
            if _cushion > _entry_px * 0.10:
                _zone = "🟢 comfortable profit zone"
            elif _pnl_usd > 0:
                _zone = "🟡 in profit — stop is below entry, protected"
            elif _cushion < _entry_px * 0.05:
                _zone = "🔴 near stop — watch closely"
            else:
                _zone = "🟡 in drawdown — stop holding"

            narrative = (
                f"{_pnl_emoji} [{ticker}] {bar_t} — POSITION LIVE | "
                f"{_opt_type} @ ${_entry_px:.2f} × {_n_contracts}ct ({_sname}) | "
                f"Stock ${close:.2f} · Option ${_cur_opt:.2f} "
                f"({_sign}{_pnl_pct:.1f}% · {_sign}${abs(_pnl_usd):.0f}) {_zone} | "
                f"Stop ${_stop_px:.2f} ({_stop_pct*100:.0f}% stop · ${_cushion:.2f} cushion · "
                f"{_pct_to_stop:.1f}% above stop){_struct_note} | "
                f"{_stage_note} | "
                f"Time-box {_time_used}/{_timebox} min — {_time_left} min left{_time_pressure} | "
                f"{_mom}"
            )
            log_event("INFO", "bar_eval", narrative)
            return

        # Scanning is narrated after the actual router evaluation, not from
        # an unrelated ORB checklist. Position narration above is unchanged.
        return

    except Exception as _be:
        logger.debug("_log_bar_thinking error: %s", _be)

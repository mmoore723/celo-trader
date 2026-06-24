"""
dashboard/pages/live_trading.py — Live Trading page.

Call render() to display this page.
"""
import json
import math
import threading
from datetime import datetime, date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import streamlit as st

from config import (get_settings, save_settings, STARTING_CAPITAL,
                    DB_PATH_PAPER, DB_PATH_LIVE, get_risk_tier)
from trading_logic import (LIVE_STATE, manual_close_position, panic_close_all,
                            close_trade_by_id, reset_session_state,
                            run_trading_loop, stop_loop)
from broker import get_clients
from database import get_trades, get_open_trades, init_db
from signals import (bars_to_df, compute_vwap, get_opening_range,
                     compute_rvol, compute_atr)
from risk import RiskManager
from backtester import Backtester
from journal_notes import build_trade_note_html, NOTE_MODAL_CSS
from dashboard.css import T
from dashboard.helpers import (
    _read_bot_state, _bot_engine_alive, generate_simulation_data,
    _load_sim_bars, _html_table, _BOT_STATE_PATH,
)
from dashboard.components.trade_plan import _generate_trade_plan, _render_trade_plan_banner


def render() -> None:
    """Render the Live Trading page."""
    import numpy as np
    from signals import (bars_to_df as _b2d,
                         compute_vwap as _compute_vwap,
                         get_opening_range as _get_or)
    from risk import RiskManager as _RMLive
    from plotly.subplots import make_subplots as _make_subplots
    
    plot_tmpl = "plotly_white"
    
    # ── Sim controls live in session_state so the right-panel widgets own them ─
    if "sim_mode"    not in st.session_state: st.session_state["sim_mode"]    = True
    if "sim_ptr_5m"  not in st.session_state: st.session_state["sim_ptr_5m"]  = 70
    if "sim_ptr_1m"  not in st.session_state: st.session_state["sim_ptr_1m"]  = 500  # full session ≤390 bars; iloc clamps to actual df length
    sim_mode   = st.session_state["sim_mode"]
    sim_ptr_5m = st.session_state["sim_ptr_5m"]
    sim_ptr_1m = st.session_state["sim_ptr_1m"]
    
    # ── Auto-refresh — native Streamlit fragment timer, no external package ─────
    # @st.fragment(run_every=N) fires every N seconds without touching session_state.
    # A timestamp guard prevents st.rerun() on the initial full-page render
    # (which would cause an infinite loop): _ar_last_full is stamped NOW so the
    # first fragment call sees gap≈0 and skips; 30 s later gap≈30 → fires.
    import time as _art
    _ar_interval = 30 if sim_mode else 60
    st.session_state["_ar_last_full"] = _art.time()   # stamp BEFORE fragment call
    
    @st.fragment(run_every=_ar_interval)
    def _live_autorefresh():
        _gap = _art.time() - st.session_state.get("_ar_last_full", 0)
        if _gap > 5:      # timer-triggered run (not the same-second full-render call)
            st.rerun()    # full page rerun — refreshes charts, bars, position, audit
    
    _live_autorefresh()
    
    # ── Daily Trade Plan — 09:15 ET trigger ──────────────────────────────────
    # The plan is generated once per trading day.  It is stored in session_state
    # so it survives page re-runs without re-fetching.  The user can dismiss it;
    # dismissal resets at midnight (new date key).
    #
    # During sim mode the plan still shows — it gives real pre-market context
    # even when the chart is running on yesterday's bars.
    try:
        import pytz as _plan_pytz
        _plan_ET  = _plan_pytz.timezone("America/New_York")
        _plan_now = datetime.now(_plan_ET)
    except ImportError:
        _plan_now = datetime.utcnow()
    
    _plan_date_key = _plan_now.strftime("%Y-%m-%d")   # changes at midnight → auto-reset
    _plan_hour     = _plan_now.hour
    _plan_minute   = _plan_now.minute
    
    # Window: 09:15–10:00 ET on live days; always open in sim (market closed)
    _in_plan_window = sim_mode or (
        _plan_hour == 9 and _plan_minute >= 15
    ) or (
        _plan_hour == 10 and _plan_minute == 0
    )
    
    # Reset if it's a new calendar day (clears dismissed flag + stale plan)
    if st.session_state.get("trade_plan_date") != _plan_date_key:
        st.session_state["trade_plan_date"]      = _plan_date_key
        st.session_state["trade_plan_data"]      = None   # will be None or a dict
        st.session_state["trade_plan_dismissed"] = False
        st.session_state["trade_plan_tried"]     = False  # reset attempt flag
    
    # Generate plans for ALL 5 Power Stocks once per day (one try only — avoids 403 spam)
    from config import TICKER_UNIVERSE as _PLAN_UNIVERSE
    if (_in_plan_window
            and not st.session_state.get("trade_plan_dismissed", False)
            and not st.session_state.get("trade_plan_tried", False)):
        st.session_state["trade_plan_tried"] = True
        # Build a dict: {ticker: plan_dict or None}
        _all_plans: dict = {}
        for _pt in _PLAN_UNIVERSE:
            try:
                _all_plans[_pt] = _generate_trade_plan(_pt)
            except Exception:
                _all_plans[_pt] = None
        st.session_state["trade_plan_data"] = _all_plans
    
    # ── Render: collapsed expander — zero vertical footprint unless opened ────
    if not st.session_state.get("trade_plan_dismissed", False) and _in_plan_window:
        _raw_plan  = st.session_state.get("trade_plan_data")
        # Migrate: old format was a single plan dict keyed by field names like
        # "ticker", "bias", etc.  New format is {ticker: plan_dict}.
        # Detect by checking whether the first key looks like a ticker symbol.
        if isinstance(_raw_plan, dict) and _raw_plan:
            _first_key = next(iter(_raw_plan))
            if _first_key not in ("SPY", "QQQ", "AAPL", "NVDA", "TSLA"):
                # Old single-plan dict — discard and let it regenerate next pass
                st.session_state["trade_plan_data"]  = None
                st.session_state["trade_plan_tried"] = False
                _raw_plan = None
        _all_plans = _raw_plan if isinstance(_raw_plan, dict) else {}
    
        # Build expander label from overall bias summary
        _bias_counts = {"BULLISH": 0, "BEARISH": 0, "NEUTRAL": 0}
        for _pd in _all_plans.values():
            if _pd:
                _bias_counts[_pd.get("bias", "NEUTRAL")] = _bias_counts.get(_pd.get("bias", "NEUTRAL"), 0) + 1
        _dominant = max(_bias_counts, key=_bias_counts.get)
        _dom_emoji = {"BULLISH": "🟢", "BEARISH": "🔴", "NEUTRAL": "⚪"}.get(_dominant, "⚪")
        _exp_label = f"📋 Today's Game Plan — Power 5 {_dom_emoji} {_dominant} lean · tap to open"
    
        with st.expander(_exp_label, expanded=False):
            # ── 5-stock card grid ────────────────────────────────────────────
            _NAMES = {"SPY": "S&P 500", "QQQ": "Nasdaq", "AAPL": "Apple",
                      "NVDA": "Nvidia", "TSLA": "Tesla"}
            _card_parts = []
            for _tk in _PLAN_UNIVERSE:
                _pd = _all_plans.get(_tk)
                if _pd:
                    _b   = _pd["bias"]
                    _be  = _pd["bias_emoji"]
                    _gp  = _pd["gap_pct"]
                    _yh  = _pd["yest_high"]
                    _yl  = _pd["yest_low"]
                    _pml = _pd["pm_last"]
                    _yc  = _pd["yest_close"]
                    # Bias pill colors
                    _bc  = "#166534" if _b == "BULLISH" else ("#991b1b" if _b == "BEARISH" else "#78350f")
                    _bbg = "#dcfce7" if _b == "BULLISH" else ("#fee2e2" if _b == "BEARISH" else "#fef3c7")
                    _bbd = "#22c55e" if _b == "BULLISH" else ("#ef4444" if _b == "BEARISH" else "#f59e0b")
                    # One-line overnight summary a middle schooler can read
                    if _gp > 0.30:
                        _ov_line = f"Jumped ${_pml:.2f} overnight (+{_gp:.1f}%) — buyers were active."
                    elif _gp < -0.30:
                        _ov_line = f"Fell to ${_pml:.2f} overnight ({_gp:.1f}%) — sellers took over."
                    else:
                        _ov_line = f"Barely moved overnight. Now at ${_pml:.2f} (was ${_yc:.2f})."
                    # What the bot is watching — plain English
                    if _b == "BULLISH":
                        _watch = (
                            f"Watching for a CALL (bet it goes up). "
                            f"Bot enters if price breaks above ${_yh:.2f} at 9:30 AM with big volume."
                        )
                    elif _b == "BEARISH":
                        _watch = (
                            f"Watching for a PUT (bet it goes down). "
                            f"Bot enters if price drops below ${_yl:.2f} at 9:30 AM with big volume."
                        )
                    else:
                        _watch = (
                            f"No clear direction yet. Bot waits to see which side breaks first — "
                            f"above ${_yh:.2f} for CALL, below ${_yl:.2f} for PUT."
                        )
                    _card_parts.append(
                        f'<div style="flex:1;min-width:150px;background:#fff;'
                        f'border:1px solid #dde4f0;border-top:3px solid {_bbd};'
                        f'border-radius:8px;padding:10px 12px;'
                        f'box-shadow:0 2px 8px rgba(10,37,64,0.06)">'
                        f'<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px">'
                        f'<div>'
                        f'<div style="font-size:.9rem;font-weight:800;color:#0a2540">{_tk}</div>'
                        f'<div style="font-size:.62rem;color:#7a93ae">{_NAMES.get(_tk,"")}</div>'
                        f'</div>'
                        f'<div style="background:{_bbg};color:{_bc};font-size:.6rem;font-weight:700;'
                        f'padding:2px 8px;border-radius:20px;white-space:nowrap">{_be} {_b}</div>'
                        f'</div>'
                        f'<div style="font-size:.68rem;color:#374151;margin-bottom:6px;line-height:1.4">'
                        f'<b>Overnight:</b> {_ov_line}</div>'
                        f'<div style="font-size:.68rem;color:#374151;line-height:1.4">'
                        f'<b>Bot watching:</b> {_watch}</div>'
                        f'</div>'
                    )
                else:
                    # No data for this ticker
                    _card_parts.append(
                        f'<div style="flex:1;min-width:150px;background:#f8faff;'
                        f'border:1px solid #dde4f0;border-radius:8px;padding:10px 12px;'
                        f'box-shadow:0 1px 3px rgba(0,0,0,0.04)">'
                        f'<div style="font-size:.9rem;font-weight:800;color:#0a2540;margin-bottom:4px">{_tk}</div>'
                        f'<div style="font-size:.65rem;color:#7a93ae">'
                        f'Pre-market data unavailable.<br>Watch the 9:30 AM breakout — '
                        f'enter whichever side moves with 2× normal volume.</div>'
                        f'</div>'
                    )
    
            st.markdown(
                f'<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px">'
                + "".join(_card_parts) +
                f'</div>',
                unsafe_allow_html=True,
            )
    
            # ── Plain-English rules reminder ─────────────────────────────────
            st.markdown(
                '<div style="font-size:.68rem;color:#7a93ae;padding:6px 4px;border-top:1px solid #dde4f0;margin-top:2px">'
                '💡 <b>How this works:</b> At 9:30 AM, the bot watches the first 5-minute candle. '
                'If it breaks the right direction with big volume, the bot buys an option contract. '
                'It exits automatically when the profit target, stop-loss, or time limit is hit — '
                'you don\'t need to do anything.'
                '</div>',
                unsafe_allow_html=True,
            )
    
            if st.button("✅ Got it — dismiss", key="btn_plan_dismiss_fallback"):
                st.session_state["trade_plan_dismissed"] = True
                st.rerun()
    
    # ── Per-ticker chart state cache ──────────────────────────────────────────
    # Prevents random ticker overwrites: bars are stored per-ticker in session_state
    # and only re-fetched when the active ticker changes or the cache is stale (> 60s).
    import time as _chart_time
    if "_chart_cache" not in st.session_state:
        st.session_state["_chart_cache"] = {}   # {ticker: {"df": df, "ts": epoch}}
    
    def _get_cached_bars(ticker: str, fetch_fn) -> pd.DataFrame:
        """Return cached bars for ticker or call fetch_fn() to refresh."""
        cache     = st.session_state["_chart_cache"]
        now_epoch = _chart_time.time()
        entry     = cache.get(ticker)
        # Cache hit: valid for 60 s during live session
        if entry and (now_epoch - entry["ts"]) < 60:
            return entry["df"]
        # Cache miss or stale: fetch fresh bars
        fresh_df = fetch_fn()
        cache[ticker] = {"df": fresh_df, "ts": now_epoch}
        # Evict stale tickers (keep only the 3 most recent)
        if len(cache) > 3:
            oldest = sorted(cache, key=lambda t: cache[t]["ts"])[0]
            cache.pop(oldest, None)
        return fresh_df
    
    # ── Data preparation ──────────────────────────────────────────────────────
    def _add_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """
        Add anchored VWAP + ±1σ/±2σ sigma bands, EMA50, and rolling RVOL proxy.
        EMA9 and EMA21 removed — institutional model uses EMA50 and VWAP
        standard-deviation bands instead of retail EMA crosses.
        """
        df = df.copy()
        if "time" not in df.columns:
            df["time"] = pd.date_range(end=datetime.now(), periods=len(df), freq="5min")
        df["time"] = pd.to_datetime(df["time"])
    
        # Anchored VWAP + ±1σ and ±2σ bands (volume-weighted std dev)
        try:
            from signals import compute_vwap_bands as _cvb
            _bands = _cvb(df, num_stds=(1, 2))
            df["vwap"]        = _bands["vwap"].ffill()
            df["vwap_upper1"] = _bands["vwap_upper1"].ffill()
            df["vwap_lower1"] = _bands["vwap_lower1"].ffill()
            df["vwap_upper2"] = _bands["vwap_upper2"].ffill()
            df["vwap_lower2"] = _bands["vwap_lower2"].ffill()
        except Exception:
            df["vwap"]        = _compute_vwap(df).ffill()
            for _col in ("vwap_upper1", "vwap_lower1", "vwap_upper2", "vwap_lower2"):
                df[_col] = df["vwap"]
    
        # EMA50 — long-term structural anchor (replaces EMA9/21 retail crosses)
        df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()
    
        # 20-bar rolling RVOL proxy (display only)
        _roll_avg  = df["volume"].rolling(20, min_periods=1).mean().shift(1).bfill()
        df["rvol"] = (df["volume"] / _roll_avg.replace(0, float("nan"))).fillna(1.0)
        return df
    
    def _compute_signals(df):
        """
        Compute the 5-signal ORB signal overlay for any given DataFrame.
        Returns (_signals, _bull_count, _overall) — same shape used in the
        right panel and mini Quad overlays.
        """
        if df is None or df.empty:
            return [], 0, "⚪ NEUTRAL — No data"
        _c_s    = float(df["close"].iloc[-1])
        _v_s    = float(df["vwap"].iloc[-1]) if "vwap" in df.columns else _c_s
        _e50_s  = float(df["ema50"].iloc[-1]) if "ema50" in df.columns else _c_s
        _vu1_s  = float(df["vwap_upper1"].iloc[-1]) if "vwap_upper1" in df.columns else _v_s
        _vl1_s  = float(df["vwap_lower1"].iloc[-1]) if "vwap_lower1" in df.columns else _v_s
        _rvol_s = float(df["rvol"].iloc[-1]) if "rvol" in df.columns else 1.0
        _ori_s  = _get_or(df)
        _orh_s  = _ori_s["high"] if _ori_s else None
        _orl_s  = _ori_s["low"]  if _ori_s else None
        _orb_s  = None
        if _orh_s and _orl_s:
            if _c_s > _orh_s:  _orb_s = "bullish"
            elif _c_s < _orl_s: _orb_s = "bearish"
        _sigs: list[tuple[str, str, str]] = []
        # Signal 1 — ORB breakout
        if _orb_s == "bullish":
            _sigs.append(("🟢", "ORB Breakout", f"Above OR High ${_orh_s:.2f} — CALL bias"))
        elif _orb_s == "bearish":
            _sigs.append(("🔴", "ORB Breakout", f"Below OR Low ${_orl_s:.2f} — PUT bias"))
        elif _orh_s:
            _sigs.append(("⚪", "ORB Forming", f"Inside range [{_orl_s:.2f}–{_orh_s:.2f}]"))
        else:
            _sigs.append(("⚪", "ORB Pending", "Opening range bar not yet seen"))
        # Signal 2 — VWAP gate
        if _c_s > _v_s:
            _sigs.append(("🟢", "Price Above VWAP", f"${_c_s:.2f} > ${_v_s:.2f} — buyers in control"))
        else:
            _sigs.append(("🔴", "Price Below VWAP", f"${_c_s:.2f} < ${_v_s:.2f} — sellers in control"))
        # Signal 3 — VWAP band position
        if _c_s > _vu1_s:
            _sigs.append(("⚪", f"Above VWAP +1σ (${_vu1_s:.2f})", "Extended — watch for reversion"))
        elif _c_s < _vl1_s:
            _sigs.append(("⚪", f"Below VWAP -1σ (${_vl1_s:.2f})", "Oversold vs VWAP"))
        else:
            _sigs.append(("🟢", "Inside VWAP ±1σ band", "Fair value zone — clean entry"))
        # Signal 4 — Relative Volume
        if _rvol_s >= 2.0:
            _sigs.append(("🟢", f"Volume {_rvol_s:.1f}× Normal", "High participation — entry eligible"))
        elif _rvol_s >= 1.2:
            _sigs.append(("⚪", f"Volume {_rvol_s:.1f}× Normal", "Volume building"))
        else:
            _sigs.append(("🔴", f"Volume {_rvol_s:.1f}× Normal", "Low participation — no entry"))
        # Signal 5 — EMA50 structural trend
        if _c_s > _e50_s:
            _sigs.append(("🟢", f"Above EMA50 (${_e50_s:.2f})", "Bullish structure"))
        else:
            _sigs.append(("🔴", f"Below EMA50 (${_e50_s:.2f})", "Bearish structure"))
        _bc = sum(1 for s in _sigs if s[0] == "🟢")
        _ov = ("🟢 BULLISH — Watching for CALL" if _bc >= 3 else
               "🔴 BEARISH — Watching for PUT"  if _bc <= 1 else
               "⚪ NEUTRAL — No clear edge")
        return _sigs, _bc, _ov
    
    # Read bot state early so _fetch_sym (current_ticker) is available for bar loading.
    # The full bot-state block below re-reads it after the learning overlay is built.
    bot = _read_bot_state()
    
    # ── Live bar loading — always uses the live Alpaca feed ───────────────────
    # sim_mode is a chart-overlay toggle ONLY and does NOT change data sources,
    # DB paths, or API calls.  The backend always runs on real market data.
    # ── Fetch bars from Alpaca with progressive fallback ──────────────────
    # 1st try : today's session (9:30–16:00 ET) via get_session_bars —
    #           internally falls back to a 2-day window if today is empty.
    # 2nd try : LIVE_STATE bars (populated by the bot's own tick loop).
    # 3rd try : explicit limit=300 fetch — widest net, no date filter.
    raw_bars          = LIVE_STATE.get("bars_5m", [])
    _session_is_live  = False
    _session_date_lbl = "Today"
    
    try:
        from broker import AlpacaClient as _DashAC
        _dash_ac   = _DashAC()
        # chart_ticker: user-selectable override for the 1m/5m charts.
        # Falls back to bot's current ticker on first load.
        _bot_ticker  = bot.get("current_ticker") or "SPY"
        if "chart_ticker" not in st.session_state:
            st.session_state["chart_ticker"] = _bot_ticker
        _fetch_sym = st.session_state.get("chart_ticker") or _bot_ticker
    
        def _do_fetch():
            """Inner fetch — tries session bars, falls back to limit-300."""
            _sb, _se, _live = _dash_ac.get_session_bars(_fetch_sym, "5Min")
            if not _se and _sb:
                return _sb, _live
            _fb2, _fe2 = _dash_ac.get_bars(_fetch_sym, "5Min", limit=300)
            if not _fe2 and _fb2:
                return _fb2, False
            return [], False
    
        # Use per-ticker cache to prevent cross-ticker data overwrites.
        # _get_cached_bars re-fetches only if ticker changed or cache > 60s old.
        def _cached_fetch():
            _bars, _live = _do_fetch()
            # Smuggle _live into the cache wrapper via a mutable container
            _cached_fetch._live = _live
            return _bars
        _cached_fetch._live = False
    
        raw_bars = _get_cached_bars(_fetch_sym, _cached_fetch)
        _session_is_live = _cached_fetch._live
    
        # Parse the first bar's date for the "Last Session" label
        if raw_bars:
            try:
                _ts0 = str(raw_bars[0].get("t", ""))
                _dt0 = _ts0[:10]   # "YYYY-MM-DD"
                if not _session_is_live and _dt0:
                    _session_date_lbl = f"Last Session · {_dt0}"
            except Exception:
                pass
    except Exception as _fetch_ex:
        import logging as _fe_log
        _fe_log.getLogger("celo_trader.dashboard").warning("Bar fetch failed: %s", _fetch_ex)
    
    if raw_bars:
        _df_raw = _b2d(raw_bars)
        # Strip orphan pre/post-market bars — keep only if they're a small stub
        # (< 10% of total or < 3 bars) so a single 08:30 candle doesn't break the scale.
        if not _df_raw.empty:
            _reg_mask = (_df_raw["time"].dt.hour > 9) | (
                (_df_raw["time"].dt.hour == 9) & (_df_raw["time"].dt.minute >= 29)
            )
            _out_count = (~_reg_mask).sum()
            if 0 < _out_count < max(3, int(len(_df_raw) * 0.10)):
                _filtered_raw = _df_raw[_reg_mask].reset_index(drop=True)
                # Only apply the filter if rows survive — an all-pre-market
                # bar list (e.g. IEX free-tier returning a single early bar)
                # must NOT collapse _df_raw to empty, or df_5m below ends up
                # empty and the iloc[-1] reads after this block raise IndexError.
                if not _filtered_raw.empty:
                    _df_raw = _filtered_raw
        df_5m = _add_indicators(_df_raw)
    else:
        df_5m = pd.DataFrame()  # no bars at all — fall through to placeholder below
    
    if df_5m.empty:
        # ── No usable bars — show a warning and an empty ET-anchored frame ─
        # Use today's 09:30 ET anchor so the x-axis at least shows market hours.
        # The _b2d() conversion is NOT needed here because we're building the
        # timestamps directly in ET tz-naive format.
        st.warning(
            "⚠️ No market data loaded — check your Alpaca API key and network "
            "connection. The chart below is a placeholder.",
            icon=None,
        )
        try:
            import pytz as _pytz
            _et_now  = datetime.now(_pytz.timezone("America/New_York"))
        except ImportError:
            import datetime as _dt_mod
            _et_now  = datetime.utcnow() - _dt_mod.timedelta(hours=4)
        _et_session_start = _et_now.replace(
            hour=9, minute=30, second=0, microsecond=0, tzinfo=None
        )
        df_5m = _add_indicators(pd.DataFrame({
            "time":   pd.date_range(
                start=_et_session_start, periods=40, freq="5min"
            ),
            "open":   float("nan"), "high": float("nan"),
            "low":    float("nan"), "close": float("nan"),
            "volume": 0,
        }))
    # ── Fetch 1-minute bars separately (same fallback chain as 5m) ──────────────
    try:
        from broker import AlpacaClient as _DashAC1m
        _ac1m = _DashAC1m()
        _sym1m = st.session_state.get("chart_ticker") or bot.get("current_ticker") or "SPY"
        _raw1m, _, _ = _ac1m.get_session_bars(_sym1m, "1Min")
        if not _raw1m:
            _raw1m, _ = _ac1m.get_bars(_sym1m, "1Min", limit=390)
        if _raw1m:
            _df1m_raw = _b2d(_raw1m)
            if not _df1m_raw.empty:
                _reg1m = (_df1m_raw["time"].dt.hour > 9) | (
                    (_df1m_raw["time"].dt.hour == 9) & (_df1m_raw["time"].dt.minute >= 29)
                )
                _out1m = (~_reg1m).sum()
                if 0 < _out1m < max(3, int(len(_df1m_raw) * 0.10)):
                    _df1m_raw = _df1m_raw[_reg1m].reset_index(drop=True)
            df_1m = _add_indicators(_df1m_raw)
        else:
            df_1m = df_5m.copy()
    except Exception:
        df_1m = df_5m.copy()
    
    # ── Live signal overlay: ORB / VWAP / Volume / Structure ─────────────────────
    _c        = float(df_5m["close"].iloc[-1])
    _v        = float(df_5m["vwap"].iloc[-1])
    _e50      = float(df_5m["ema50"].iloc[-1]) if "ema50" in df_5m.columns else _c
    _vu1      = float(df_5m["vwap_upper1"].iloc[-1]) if "vwap_upper1" in df_5m.columns else _v
    _vl1      = float(df_5m["vwap_lower1"].iloc[-1]) if "vwap_lower1" in df_5m.columns else _v
    _vol_rvol = float(df_5m["rvol"].iloc[-1]) if "rvol" in df_5m.columns else 1.0
    # Opening range state
    _or_info = _get_or(df_5m)
    _or_high = _or_info["high"] if _or_info else None
    _or_low  = _or_info["low"]  if _or_info else None
    _orb_dir = None
    if _or_high is not None and _or_low is not None:
        if _c > _or_high:   _orb_dir = "bullish"
        elif _c < _or_low:  _orb_dir = "bearish"
    _signals = []
    # Signal 1 — ORB breakout
    if _orb_dir == "bullish":
        _signals.append(("🟢", "ORB Breakout", f"Above OR High ${_or_high:.2f} — CALL bias"))
    elif _orb_dir == "bearish":
        _signals.append(("🔴", "ORB Breakout", f"Below OR Low ${_or_low:.2f} — PUT bias"))
    elif _or_high:
        _signals.append(("⚪", "ORB Forming", f"Inside range [{_or_low:.2f}–{_or_high:.2f}] — no signal"))
    else:
        _signals.append(("⚪", "ORB Pending", "Opening range bar not yet seen"))
    # Signal 2 — VWAP gate
    if _c > _v:  _signals.append(("🟢", "Price Above VWAP", f"${_c:.2f} > ${_v:.2f} — buyers in control"))
    else:        _signals.append(("🔴", "Price Below VWAP", f"${_c:.2f} < ${_v:.2f} — sellers in control"))
    # Signal 3 — VWAP band position (+1σ/+2σ indicates extended; -1σ/-2σ indicates oversold)
    if _c > _vu1:
        _signals.append(("⚪", f"Price above VWAP +1σ (${_vu1:.2f})", "Extended — watch for reversion, avoid chasing"))
    elif _c < _vl1:
        _signals.append(("⚪", f"Price below VWAP -1σ (${_vl1:.2f})", "Oversold vs VWAP — potential bounce or breakdown zone"))
    else:
        _signals.append(("🟢", f"Price inside VWAP ±1σ band", f"Fair value zone — clean entry conditions"))
    # Signal 4 — Relative Volume gate
    if _vol_rvol >= 2.0:   _signals.append(("🟢", f"Volume {_vol_rvol:.1f}× Normal", "High participation — entry eligible"))
    elif _vol_rvol >= 1.2: _signals.append(("⚪", f"Volume {_vol_rvol:.1f}× Normal", "Volume building — watching for surge"))
    else:                  _signals.append(("🔴", f"Volume {_vol_rvol:.1f}× Normal", "Low participation — no entry"))
    # Signal 5 — EMA50 structural trend (replaces EMA9/21 retail cross)
    if _c > _e50:   _signals.append(("🟢", f"Above EMA50 (${_e50:.2f})", "Price above long-term anchor — bullish structure"))
    else:           _signals.append(("🔴", f"Below EMA50 (${_e50:.2f})", "Price below long-term anchor — bearish structure"))
    _bull_count = sum(1 for s in _signals if s[0] == "🟢")
    _overall    = ("🟢 BULLISH — Watching for CALL" if _bull_count >= 3 else
                   "🔴 BEARISH — Watching for PUT"  if _bull_count <= 1 else
                   "⚪ NEUTRAL — No clear edge")
    # Signal overlay is rendered in col_pos below the action buttons
    
    # ── Resolve live bot state ────────────────────────────────────────────────
    open_trade = get_open_trade() or LIVE_STATE.get("open_trade")
    bot        = _read_bot_state()
    _mkt_open  = bot["market_open"]
    
    # FIX: a trade that closed moments ago (e.g. via the 45-min time-box exit)
    # used to "disappear" from the chart entirely. Once it closes, open_trade
    # becomes None and current_ticker often resets to None too (e.g. right
    # after a bot restart, before the scanner repopulates), so the fallback
    # chain fell through to session_state/watchlist and the chart jumped to
    # a different symbol — taking that trade's entry/exit circles with it.
    # New step 3 below keeps the chart pinned to the ticker of the most
    # recently CLOSED trade for the rest of today, so its circles stay
    # visible until the bot actively focuses on something else.
    _last_closed = None
    try:
        _recent_closed = get_all_trades(limit=1)
        if _recent_closed and str(_recent_closed[0].get("exit_time", "")).startswith(date.today().isoformat()):
            _last_closed = _recent_closed[0].get("ticker")
    except Exception:
        _last_closed = None
    
    # Ticker fallback chain so the label is never just "—" after hours:
    #   1. bot_state.json current_ticker  (set while market is open)
    #   2. open trade ticker              (if a position is held overnight)
    #   3. most recently CLOSED trade's ticker, if closed earlier today
    #   4. session_state last_ticker      (persisted from the most recent live session)
    #   5. config watchlist first symbol  (static default)
    # FIX: open-trade ticker now OUTRANKS session_state's _last_ticker.
    # _last_ticker holds whatever symbol the SCANNER was cycling through when
    # the market closed (e.g. SPY), which is unrelated to what's actually
    # HELD. With the old order, the topbar/chart/ticker badge showed that
    # stale scanner ticker instead of the open position's real ticker (e.g.
    # IWM) — making it look like the bot wasn't holding anything, or was
    # holding the wrong symbol, and causing the chart + _today_trades filter
    # below to load the wrong ticker's data entirely.
    _raw_ticker = (
        bot.get("current_ticker")
        or (open_trade.get("ticker") if open_trade else None)
        or _last_closed
        or st.session_state.get("_last_ticker")
        or get_settings().get("watchlist", ["SPY"])[0]
    )
    _ticker = _raw_ticker or "SPY"
    # Persist whenever we have a real value so the next after-hours load has it
    if bot.get("current_ticker"):
        st.session_state["_last_ticker"] = bot["current_ticker"]
    _signal    = (bot.get("last_signal") or "none").upper()
    _sig_pill  = ("pill-bull" if _signal == "BULLISH" else
                  "pill-bear" if _signal == "BEARISH" else "pill-wait")
    _spnl      = bot["session_pnl"]
    _bal       = bot["account_balance"]
    _status    = bot["status"]
    _last_upd  = bot["last_update"]
    _last_strat = bot.get("last_strategy_id") or "—"
    
    # ── Market-closed override: never show RUNNING when market is closed ──────
    if not _mkt_open and _status not in ("idle", "standby", "sim_active"):
        _status = "standby"
    
    # In sim mode override balance/P&L with the auto-sim-signal results so the
    # metric cards show a live balance instead of the static $5,000 starting capital.
    # FIX: only do this when there is NO real open trade. Previously this fired
    # whenever the "🎓 Simulation Mode" checkbox was on (the default), which
    # clobbered the real bot's balance/status/last-update with sim placeholders
    # ($5,000.00 / "SIM ACTIVE" / "Simulation") even while a real position was
    # open — causing the Balance card to disagree with the sidebar and
    # Performance page (which read the real bot_state.json balance).
    if sim_mode and not open_trade:
        _sim_bal_now  = st.session_state.get("sim_balance", float(STARTING_CAPITAL))
        _sim_pnl_now  = _sim_bal_now - float(STARTING_CAPITAL)
        _bal          = _sim_bal_now
        _spnl         = _sim_pnl_now
        _status       = "sim_active"
        _last_upd     = "Simulation"
    
    # _session_is_live and _session_date_lbl are set by the live bar loading above.
    # Provide safe defaults in case the fetch block short-circuited.
    _session_is_live  = locals().get("_session_is_live", _mkt_open)
    _session_date_lbl = locals().get("_session_date_lbl", "Today")
    
    # ── CELO TRADER branding banner ───────────────────────────────────────────
    # Full-width dark card with metallic serif text + neon-blue glow.
    # Sits above the command center header so it's the very first thing visible.
    st.markdown("""
    <div class="ct-brand-wrap">
      <div class="ct-brand">CELO TRADER</div>
      <div class="ct-sub">Autonomous Options Engine · Power 5 Universe</div>
    </div>
    """, unsafe_allow_html=True)
    
    # ── Command center header ─────────────────────────────────────────────────
    # Big 40pt P&L display + active state chip + connection health dots.
    # Designed to be the FIRST thing visible on the Live Trading page —
    # user should never have to scroll to know the bot's current status.
    _pnl_color  = "#1a7f37" if _spnl >= 0 else "#cf222e"
    _pnl_sign   = "+" if _spnl >= 0 else ""
    _alive_hdr  = _bot_engine_alive(bot.get("last_update"))
    _network_ok = bot.get("network_ok", True)
    # Options Buying Power — red below $100 (next order will likely be rejected)
    _obp_hdr       = float(bot.get("options_buying_power", 0))
    _obp_hdr_color = "#cf222e" if _obp_hdr < 100 else "#1f2328"
    _obp_hdr_note  = "⚠ Low" if _obp_hdr < 100 else ("Alpaca options BP")
    # Alpaca API health: engine alive AND last network call succeeded
    _alpaca_dot_color = "#00e676" if (_alive_hdr and _network_ok) else "#cf222e"
    _alpaca_dot_label = "Alpaca API ✓" if (_alive_hdr and _network_ok) else "Alpaca API ✗"
    # Data stream health: engine alive AND market is open (data flows only during session)
    _stream_dot_color = "#00e676" if (_alive_hdr and _mkt_open) else ("#ffb300" if not _mkt_open else "#cf222e")
    _stream_dot_label = "Data Stream ✓" if (_alive_hdr and _mkt_open) else ("Data Stream · Mkt Closed" if not _mkt_open else "Data Stream ✗")
    
    _state_chip_map = {
        "scanning":     ("#2ea043", "#e6f4ea", "🔍 SCANNING"),
        "in_trade":     ("#0969da", "#ddf4ff", "📈 IN TRADE"),
        "halted":       ("#cf222e", "#ffebe9", "🛑 HALTED"),
        "session_cutoff": ("#b08800", "#fff8c5", "⏰ SESSION CUTOFF"),
        "market_closed": ("#6e7681", "#f6f8fa", "🌙 MKT CLOSED"),
        "sim_active":   ("#8250df", "#fbefff", "🎓 SIM"),
        "standby":      ("#6e7681", "#f6f8fa", "💤 STANDBY"),
    }
    _chip_bdr, _chip_bg, _chip_txt = _state_chip_map.get(
        _status, ("#6e7681", "#f6f8fa", _status.upper())
    )
    
    # ── Command center header ─────────────────────────────────────────────────
    # Kill-lock check: show banner if the 24-hour loss cap has triggered.
    from risk import check_kill_lock as _ckl
    _kl_locked, _kl_reason = _ckl()
    
    # ── Sleek command bar: Bot State · Connections · Capital ─────────────────
    # Session P&L is shown in the topbar below so it shares the same row as
    # Market Open status. This bar handles everything else.
    st.markdown(f"""
    <div style="
      background:linear-gradient(135deg,#f8faff 0%,#ffffff 60%,#f4f7fd 100%);
      border:1px solid #dde4f0;border-radius:8px;
      box-shadow:0 2px 10px rgba(10,37,64,0.07),0 1px 3px rgba(0,0,0,0.04);
      padding:7px 14px;display:flex;align-items:center;gap:14px;flex-wrap:nowrap;overflow:hidden;
      margin-bottom:4px;
    ">
      <!-- Bot State chip -->
      <div style="flex:0 0 auto;text-align:center">
    <div style="font-size:9px;font-weight:700;color:#7a93ae;text-transform:uppercase;letter-spacing:.08em;margin-bottom:3px">Bot State</div>
    <div style="display:inline-block;padding:3px 12px;border-radius:20px;
      border:1.5px solid {_chip_bdr};background:{_chip_bg};
      font-size:12px;font-weight:700;color:{_chip_bdr};white-space:nowrap">{_chip_txt}</div>
      </div>
      <div style="width:1px;height:38px;background:#dde4f0;flex-shrink:0"></div>
      <!-- Connection health dots -->
      <div style="flex:0 0 auto">
    <div style="font-size:9px;font-weight:700;color:#7a93ae;text-transform:uppercase;letter-spacing:.08em;margin-bottom:4px">Connections</div>
    <div style="display:flex;flex-direction:column;gap:3px">
      <div style="display:flex;align-items:center;gap:5px;font-size:11px;font-weight:600;color:#0a2540">
        <div style="width:8px;height:8px;border-radius:50%;background:{_alpaca_dot_color};flex-shrink:0"></div>{_alpaca_dot_label}
      </div>
      <div style="display:flex;align-items:center;gap:5px;font-size:11px;font-weight:600;color:#0a2540">
        <div style="width:8px;height:8px;border-radius:50%;background:{_stream_dot_color};flex-shrink:0"></div>{_stream_dot_label}
      </div>
    </div>
      </div>
      <div style="width:1px;height:38px;background:#dde4f0;flex-shrink:0"></div>
      <!-- Capital: Options BP (primary) + Balance -->
      <div style="flex:0 0 auto;text-align:center"><div style="font-size:9px;font-weight:700;color:#7a93ae;text-transform:uppercase;letter-spacing:.08em;margin-bottom:1px">Capital</div><div style="font-size:20px;font-weight:800;line-height:1;color:{_obp_hdr_color}">${_obp_hdr:,.2f}<span style="font-size:9px;font-weight:600;color:{_obp_hdr_color};margin-left:2px">{_obp_hdr_note}</span></div><div style="font-size:9px;color:#7a93ae;margin-top:1px">Bal <span style="font-weight:700;color:#0a2540">${_bal:,.2f}</span>&nbsp;·&nbsp;{_ticker}&nbsp;·&nbsp;{_last_upd}{"&nbsp;🔒" if _kl_locked else ""}</div></div>
      <div style="flex:1 1 0"></div>
    </div>
    {"<div style='font-size:9px;color:#dc2626;font-weight:700;margin-top:2px;padding-left:4px'>🔒 " + _kl_reason + "</div>" if _kl_locked else ""}
    """, unsafe_allow_html=True)
    
    # ── Network warning — shown inline only when Alpaca is unreachable ───────
    if not _network_ok:
        st.warning(
            "⚠️ **Network issue** — Alpaca API unreachable. "
            "No orders can be placed. Bot retries automatically.",
            icon=None,
        )
    
    # ── Topbar strip ──────────────────────────────────────────────────────────
    # Market state — green "Market Open" or prominent red "MARKET CLOSED"
    if _mkt_open:
        _mkt_badge = f'<span style="color:{T["green"]};font-weight:600">● Market Open</span>'
    else:
        _mkt_badge = (
            f'<span style="background:{T["red"]};color:#fff;font-weight:700;'
            f'padding:2px 8px;border-radius:4px;font-size:.62rem">MARKET CLOSED</span>'
            f'&nbsp;<span style="font-size:.6rem;color:{T["muted"]}">{_session_date_lbl}</span>'
        )
    
    # Strategy ID pill in topbar (shows which router module last fired)
    _strat_color = {
        "INST_ORB": "#f59e0b",   # amber   — morning breakout
        "BOS_MSS":  "#818cf8",   # indigo  — structure shift
        "VWAP_PB":  "#06b6d4",   # cyan    — VWAP pullback
        "FVG":      "#ec4899",   # pink    — fair value gap
        "MID_BRK":  "#ef4444",   # red     — mid-day breakdown (bearish)
        "AFT_REV":  "#22c55e",   # green   — afternoon reversal (bullish)
    }.get(_last_strat, T["muted"])
    
    _topbar_status_label = {
        "scanning": "SCANNING", "in_trade": "IN TRADE", "halted": "HALTED",
        "idle": "IDLE", "standby": "STANDBY · OUTSIDE WINDOW",
        "sim_active": "SIM ACTIVE", "market_closed": "MKT CLOSED", "error": "ERROR",
    }.get(_status, _status.upper().replace("_", " "))
    
    # ── Topbar: ticker picker (left) + status strip (right) ──────────────────
    # The ticker selectbox IS the topbar ticker badge — selecting a new symbol
    # immediately reloads the 1m and 5m chart data for that ticker.
    # CSS below strips all default selectbox chrome so it looks like a plain
    # bold ticker label that happens to be interactive.
    st.markdown("""
    <style>
    /* Ticker picker — strip to bare text, match .tb-ticker style */
    div[data-testid="stSelectbox"].ct-ticker-pick > label {display:none}
    div[data-testid="stSelectbox"].ct-ticker-pick div[data-baseweb="select"] {
      background:transparent !important;
      border:none !important;
      box-shadow:none !important;
      min-height:0 !important;
    }
    div[data-testid="stSelectbox"].ct-ticker-pick div[data-baseweb="select"] > div {
      background:transparent !important;
      border:none !important;
      padding:0 4px 0 0 !important;
      font-family:'Syne',sans-serif !important;
      font-size:.95rem !important;
      font-weight:700 !important;
      color:#0a2540 !important;
      min-height:0 !important;
      cursor:pointer !important;
    }
    div[data-testid="stSelectbox"].ct-ticker-pick svg {
      color:#0a2540 !important;
      width:14px !important;
      height:14px !important;
    }
    </style>
    """, unsafe_allow_html=True)
    
    _tb_ticker_col, _tb_rest_col = st.columns([1, 11], gap="small")
    with _tb_ticker_col:
        try:
            from config import TICKER_UNIVERSE as _TU2
        except Exception:
            _TU2 = ["SPY", "QQQ", "AAPL", "NVDA", "TSLA"]
        _cur_ct2 = st.session_state.get("chart_ticker", "SPY")
        _ct_opts2 = list(dict.fromkeys([_cur_ct2] + _TU2))
        st.selectbox(
            "chart_ticker_pick",
            options=_ct_opts2,
            key="chart_ticker",
            label_visibility="collapsed",
            help="Change chart ticker",
        )
        # Inject class onto the last selectbox so CSS targets only this one
        st.markdown(
            "<script>document.querySelectorAll('[data-testid=\"stSelectbox\"]')"
            ".forEach((el,i,arr)=>{if(i===arr.length-1||arr.length===1)"
            "el.classList.add('ct-ticker-pick');})</script>",
            unsafe_allow_html=True,
        )
    with _tb_rest_col:
        st.markdown(f"""
    <div class="live-topbar" style="margin-top:0">
      <span class="tb-sep"></span>
      <!-- Session P&L -->
      <div style="flex:0 0 auto;display:flex;flex-direction:column;justify-content:center">
    <div class="tb-pnl-lbl">Session P&amp;L</div>
    <div class="tb-pnl-val" style="color:{_pnl_color}">{_pnl_sign}${_spnl:,.2f}</div>
      </div>
      <span class="tb-sep"></span>
      <span class="pill {_sig_pill}">{_signal} signal</span>
      <span style="font-size:.61rem;color:{T['muted']}">VWAP · ORB · Volume Gate</span>
      <span class="tb-sep"></span>
      <span style="font-size:.6rem;font-weight:700;color:{_strat_color};
        background:rgba(10,37,64,.06);padding:2px 6px;border-radius:4px;
        text-transform:uppercase;letter-spacing:.06em">{_last_strat}</span>
      <span class="tb-sep"></span>
      {_mkt_badge}
      <div class="tb-right">
    <div class="live-dot" style="background:{'#00e676' if _mkt_open else T['red']}"></div>
    <span>{_topbar_status_label} · {_last_upd}</span>
      </div>
    </div>
    """, unsafe_allow_html=True)
    
    # ── Single 8-column metric row ────────────────────────────────────────────
    # All live metrics on ONE row: Market · Ticker · Signal · Buying Power ·
    # Last Update · Contract Bot · Risk Budget · Max Affordable Premium.
    # Keeps the cockpit compact — no scroll needed to see every number.
    _mkt_cls    = "c-grn" if _mkt_open else "c-red"
    _mkt_lbl    = "Open" if _mkt_open else "Closed"
    _obp = _sidebar_bot.get("options_buying_power", 0)
    _obp_cls = "c-red" if _obp < 100 else "c-grn"
    
    # Contract-bot evaluation fields
    _last_eval_ticker   = bot.get("last_eval_ticker")
    _last_eval_premium  = bot.get("last_eval_premium")
    _last_eval_eff_entry= bot.get("last_eval_eff_entry")
    _last_eval_strike   = bot.get("last_eval_strike")
    _last_eval_opt      = (bot.get("last_eval_opt_type") or "").upper()
    _last_eval_time     = bot.get("last_eval_time") or "—"
    _risk_budget        = bot.get("risk_budget_usd", 0.0)
    _max_afford        = bot.get("max_affordable_premium", 0.0)
    
    if _last_eval_ticker and _last_eval_premium is not None:
        _eval_label = f"{_last_eval_ticker} {_last_eval_opt} · ${_last_eval_premium:.2f}"
        _eval_sub   = f"as of {_last_eval_time} ET"
    else:
        _eval_label = "—"
        _eval_sub   = "No contract evaluated"
    
    # Flag max-affordable red when last-evaluated premium exceeds it (SIZING_ZERO)
    _afford_cls = "mv c-red" if (
        _last_eval_premium is not None and _max_afford > 0 and _last_eval_premium > _max_afford
    ) else "mv"
    
    _sig_color = T['green'] if _signal == 'BULLISH' else T['red'] if _signal == 'BEARISH' else T['muted']
    
    # (metric row moved inside col_chart below — see "6-col metric row" comment)
    
    # ── Layout: charts (left 3) | position panel (right 1) ───────────────────
    col_chart, col_pos = st.columns([3, 1], gap="small")
    
    # ── Choose which timeframe to display ────────────────────────────────────
    with col_chart:
        _tf_col, _ref_col = st.columns([5, 1], gap="small")
        with _tf_col:
            tf_sel = st.radio(
                "Timeframe",
                ["5m Chart", "1m Chart", "Quad (4 Charts)"],
                index=2,          # Default to Quad — primary view per spec
                horizontal=True, label_visibility="collapsed",
            )
        with _ref_col:
            # 🔄 Refresh — clears the bar cache so the next render re-fetches
            # from Alpaca.  Use this when the chart is stuck on a stale session
            # (e.g. showing yesterday after the new market session opens).
            if st.button("🔄 Refresh", key="btn_chart_refresh", help="Clear chart cache and re-fetch latest bars"):
                st.session_state["_chart_cache"]     = {}
                st.session_state["sim_ptr_last"]     = -1   # force sim engine re-run
                st.session_state["sim_trades"]       = []
                st.session_state["sim_balance"]      = float(STARTING_CAPITAL)
                st.session_state["sim_session_date"] = date.today().isoformat()
                st.rerun()
    
    # ── Resolve display df ────────────────────────────────────────────────────
    df_display = df_1m if tf_sel == "1m Chart" else df_5m
    
    # ── Position math ─────────────────────────────────────────────────────────
    _rm    = _RMLive()
    s      = get_settings()
    _ep    = open_trade["entry_price"] if open_trade else float(df_display["close"].iloc[-1])
    _sl    = _rm.stop_loss_price(_ep)
    _tp    = _rm.take_profit_price(_ep)
    _peak  = LIVE_STATE.get("peak_price") or _ep
    _trail = _peak * (1 - float(s.get("trail_stop_pct", 0.25)))
    _prog  = max(0, min(100, (_ep - _sl) / max(_tp - _sl, 0.0001) * 100))
    # ── Compute display values (needed by both columns) ───────────────────────
    _cur_px  = float(df_display["close"].iloc[-1])
    
    _ep_show = _ep if open_trade else None
    _sl_show = _sl if open_trade else None
    _tp_show = _tp if open_trade else None
    _tr_show = _trail if open_trade else None
    _show_levels = bool(open_trade)
    # Is the open position a SIM_ trade (entry_price stored as UNDERLYING
    # stock price) or a REAL trade (entry_price stored as OPTION PREMIUM)?
    # See database.py / dashboard.py ~4017 comment on this dual convention.
    _is_sim_open = bool(open_trade) and str(open_trade.get("contract_symbol", "")).startswith("SIM_")
    _levels_on_chart_scale = _is_sim_open
    
    # The bot runs as a SEPARATE PROCESS with its own LIVE_STATE — this
    # dashboard process's LIVE_STATE never sees the bot's writes directly.
    # trading_logic._manage_open_position() bridges the live option premium
    # across processes by persisting "current_option_price"/
    # "current_option_price_time" into bot_state.json every tick (and
    # preserves them through the market-closed state write), so read it from
    # `bot` (= _read_bot_state()) instead of LIVE_STATE. If the market is
    # closed or the bot hasn't ticked yet, this is simply the LAST KNOWN
    # premium rather than missing data.
    _cur_opt_px      = bot.get("current_option_price")
    _cur_opt_px_time = bot.get("current_option_price_time")
    
    # FIX: For REAL trades, _ep_show/entry_price is the OPTION PREMIUM
    # (e.g. $4.50), not the underlying stock price (_cur_px, e.g. $737.28).
    # P&L must compare the option's CURRENT premium against the option's
    # ENTRY premium. Mixing _cur_px with _ep_show here previously produced
    # an absurd "+$73278.00" unrealised P&L.
    if not _show_levels:
        _pnl_unr = 0.0
    elif _levels_on_chart_scale:
        # SIM/ghost trades: _ep_show is on the same (underlying-price) scale as _cur_px.
        _pnl_unr = (_cur_px - _ep_show) * 100
    else:
        _contracts = open_trade.get("contracts", 1) if open_trade else 1
        _pnl_unr = (_cur_opt_px - _ep_show) * _contracts * 100 if _cur_opt_px else 0.0
    
    # "Current" price shown in the position panel — underlying price for
    # SIM/ghost trades (same scale as entry), option premium for real trades,
    # falling back to the entry price as a placeholder before the bot's first
    # tick has published a premium.
    _cur_px_show = _cur_px if _levels_on_chart_scale else (_cur_opt_px if _cur_opt_px else _ep_show)
    
    _prog_v  = max(0.0, min(100.0, (_ep_show - _sl_show) / max(_tp_show - _sl_show, 1e-9) * 100)) if _show_levels else 0.0
    
    # ── Signal basis values (ORB-centric, RSI/MACD removed) ──────────────────
    _vol_ratio  = _vol_rvol          # RVOL proxy already computed above
    _above_vwap = _c > _v
    _ema_bull   = _c > _e50          # EMA9/21 removed; use price vs EMA50 as trend flag
    _orb_active = _orb_dir is not None
    
    with col_chart:
        # ── Shared style helpers ──────────────────────────────────────────────
        _base_layout = dict(
            template="plotly_white",
            paper_bgcolor="white",
            plot_bgcolor="white",
            showlegend=False,
            font_color="black",
            font=dict(color="black", family="Arial", size=12),
            # "x unified" merges all traces into one tooltip box at the hovered
            # timestamp — eliminates the per-series label clutter that appears
            # with hovermode="x" or "closest".
            hovermode="x unified",
            hoverlabel=dict(
                bgcolor="rgba(255,255,255,0.92)",
                bordercolor="rgba(0,0,0,0.18)",
                font=dict(color="black", size=11, family="Arial"),
            ),
            xaxis=dict(
                spikemode="across",
                spikesnap="cursor",
                spikecolor="rgba(0,0,0,0.35)",
                spikethickness=1,
                spikedash="dot",
            ),
        )
    
        def _apply_contrast(fig: go.Figure) -> go.Figure:
            # Use regular-weight Arial — "Arial Black" causes number overlap
            # when prices are close together on the y-axis.
            fig.update_xaxes(tickfont=dict(color="black", size=10, family="Arial"),
                             gridcolor="rgba(0,0,0,0.06)")
            fig.update_yaxes(tickfont=dict(color="black", size=10, family="Arial"),
                             gridcolor="rgba(0,0,0,0.06)")
            fig.update_layout(font_color="black",
                              plot_bgcolor="white", paper_bgcolor="white")
            return fig
    
        # ── Institutional structure overlays ──────────────────────────────────
        def _add_structure_overlays(fig: go.Figure, df: pd.DataFrame) -> go.Figure:
            """
            Detect and draw institutional price structures when the math applies.
            Draws:
              1. Swing High / Low point labels (HH / LH / HL / LL)
              2. Resistance trendline connecting last 3 swing highs
              3. Support trendline connecting last 3 swing lows
              4. Parallel ascending / descending channel label (when both slopes match)
              5. Fibonacci retracement (0 / 23.6 / 38.2 / 50 / 61.8 / 78.6 / 100%)
                 anchored to the most recent major swing high↔low pair.
    
            Guards: skips silently when fewer than 8 bars are present, or when
            fewer than 2 swing pivots are found (prevents clutter on thin data).
            """
            if df is None or len(df) < 8:
                return fig
    
            try:
                from strategy_router import _find_swings as _fs
            except ImportError:
                return fig
    
            swings = _fs(df, pivot_bars=2)
            highs  = [(i, float(p)) for i, p, t in swings if t == "high"]
            lows   = [(i, float(p)) for i, p, t in swings if t == "low"]
    
            # ── 1. Label Swing Highs (HH or LH) ───────────────────────────
            for n, (idx, price) in enumerate(highs):
                if idx >= len(df):
                    continue
                _ts  = df.iloc[idx]["time"]
                if n == 0:
                    _lbl, _col = "SH", "#f59e0b"        # first pivot = Swing High
                elif price > highs[n - 1][1]:
                    _lbl, _col = "HH", "#10b981"        # Higher High — bullish structure
                else:
                    _lbl, _col = "LH", "#f43f5e"        # Lower High — bearish structure
                fig.add_annotation(
                    x=_ts, y=price,
                    text=_lbl,                          # no bold — lighter label
                    showarrow=True, arrowhead=2, arrowwidth=1,
                    arrowcolor=_col, ax=0, ay=-26,
                    font=dict(color=_col, size=8, family="Arial"),
                    row=1, col=1,
                )
    
            # ── 2. Label Swing Lows (HL or LL) ────────────────────────────
            for n, (idx, price) in enumerate(lows):
                if idx >= len(df):
                    continue
                _ts  = df.iloc[idx]["time"]
                if n == 0:
                    _lbl, _col = "SL", "#818cf8"        # first pivot = Swing Low
                elif price > lows[n - 1][1]:
                    _lbl, _col = "HL", "#10b981"        # Higher Low — bullish continuation
                else:
                    _lbl, _col = "LL", "#f43f5e"        # Lower Low — bearish continuation
                fig.add_annotation(
                    x=_ts, y=price,
                    text=_lbl,                          # no bold — lighter label
                    showarrow=True, arrowhead=2, arrowwidth=1,
                    arrowcolor=_col, ax=0, ay=26,
                    font=dict(color=_col, size=8, family="Arial"),
                    row=1, col=1,
                )
    
            # ── 3+4. Trendlines + Channel label ───────────────────────────
            # Fits a least-squares line through the last ≤3 swing highs/lows.
            # Only draws a line when at least 2 points are available.
            def _draw_trendline(pts: list, color: str, dash: str):
                """Draw a best-fit trendline; return its slope (pts/sec) or None."""
                if len(pts) < 2:
                    return None
                _pts  = pts[-3:]    # use at most last 3 pivots
                _ts   = [df.iloc[i]["time"] for i, _ in _pts if i < len(df)]
                _px   = [p for i, p in _pts if i < len(df)]
                if len(_ts) < 2:
                    return None
                _t0   = _ts[0]
                _xnum = [(t - _t0).total_seconds() for t in _ts]
                if max(_xnum) == 0:
                    return None
                _m, _b = np.polyfit(_xnum, _px, 1)
                # Extend line from first pivot to last bar
                _x_end = (df["time"].iloc[-1] - _t0).total_seconds()
                _y0    = float(_b)
                _y_end = float(_m * _x_end + _b)
                fig.add_shape(
                    type="line",
                    x0=_t0, x1=df["time"].iloc[-1],
                    y0=_y0, y1=_y_end,
                    line=dict(color=color, width=1.3, dash=dash),
                    row=1, col=1,
                )
                return _m
    
            _slope_hi = _draw_trendline(highs, "#f59e0b", "dot")   # amber resistance
            _slope_lo = _draw_trendline(lows,  "#818cf8", "dot")   # indigo support
    
            # Annotate channel type when both trendlines share the same slope sign
            if _slope_hi is not None and _slope_lo is not None:
                _tol = 1e-8
                if _slope_hi > _tol and _slope_lo > _tol:
                    _ch_lbl = "↗ Ascending Channel"
                elif _slope_hi < -_tol and _slope_lo < -_tol:
                    _ch_lbl = "↘ Descending Channel"
                else:
                    _ch_lbl = None
                if _ch_lbl:
                    fig.add_annotation(
                        x=df["time"].iloc[-1], y=float(df["high"].max()),
                        text=f"<b>{_ch_lbl}</b>",
                        showarrow=False, xanchor="right", yanchor="bottom",
                        font=dict(color="#94a3b8", size=8, family="Arial"),
                        row=1, col=1,
                    )
    
            # ── 5. Fibonacci retracement ───────────────────────────────────
            # Anchored from the most recent swing low→high (or high→low).
            if highs and lows:
                _hi_idx, _hi_px = highs[-1]
                _lo_idx, _lo_px = lows[-1]
                _rng = abs(_hi_px - _lo_px)
                if _rng < _lo_px * 0.002:          # skip trivial <0.2% swings
                    return fig
                # Determine retrace direction from which swing came last
                if _hi_idx > _lo_idx:
                    _fib_lo, _fib_hi = _lo_px, _hi_px     # bullish move → bearish retrace
                    _retrace_dir = "↓ Fib retrace"
                else:
                    _fib_lo, _fib_hi = _hi_px, _lo_px     # bearish move → bullish retrace
                    _retrace_dir = "↑ Fib retrace"
    
                _FIB_LEVELS = [
                    (0.000, "rgba(140,140,140,.35)"),
                    (0.236, "rgba(255,165,  0,.45)"),
                    (0.382, "rgba( 16,185,129,.55)"),
                    (0.500, "rgba(  0,160,230,.65)"),
                    (0.618, "rgba( 16,185,129,.55)"),
                    (0.786, "rgba(255,165,  0,.45)"),
                    (1.000, "rgba(140,140,140,.35)"),
                ]
                for _lvl, _clr in _FIB_LEVELS:
                    _fpx = _fib_hi - (_fib_hi - _fib_lo) * _lvl
                    fig.add_hline(
                        y=_fpx,
                        line_color=_clr,
                        line_dash="longdash",
                        line_width=0.9,
                        annotation_text=f"{_lvl:.3f}  ${_fpx:.2f}",
                        annotation_font_color=_clr,
                        annotation_font_size=7,
                        annotation_position="left",
                        row=1, col=1,
                    )
    
            return fig
    
        # ── ORB live chart: candlestick + VWAP + ORB shading + volume gate ────
        def _orb_live_fig(df: pd.DataFrame, show_lvls: bool = False,
                          chart_title: str = "",
                          today_trades: list = None,
                          show_overlays: bool = True,
                          compact: bool = False) -> go.Figure:
            """
            make_subplots(2 rows):
              Row 1 — Candlestick (always) + indicators/markers (only when show_overlays=True).
              Row 2 — Volume bars (always) + avg line + 200% gate (only when show_overlays=True).
    
            show_overlays is driven by the 'Simulation Mode' checkbox:
              True  → draw VWAP, EMA9/21, ORB zone, TP/SL, BUY/SELL markers.
              False → clean candles + raw volume only.
            """
            if today_trades is None:
                today_trades = []
    
            # compact=True used by quad layout — smaller volume panel, shorter height
            _row_h = [0.80, 0.20] if compact else [0.72, 0.28]
            fig = _make_subplots(
                rows=2, cols=1,
                shared_xaxes=True,
                row_heights=_row_h,
                vertical_spacing=0.02 if compact else 0.03,
            )
    
            # ── Row 1: Candlestick ─────────────────────────────────────────
            fig.add_trace(go.Candlestick(
                x=df["time"],
                open=df["open"], high=df["high"],
                low=df["low"],   close=df["close"],
                name="Price",
                increasing_line_color=T["green"], increasing_fillcolor=T["green"],
                decreasing_line_color=T["red"],   decreasing_fillcolor=T["red"],
                line=dict(width=1.5),
                # Show OHLC values in the unified hover box; suppress the default
                # Plotly candlestick tooltip that duplicates fields redundantly.
                hoverinfo="x+y",
            ), row=1, col=1)
    
            # ── Row 1: VWAP (bold solid — the most important overlay) ──────
            if show_overlays:
                fig.add_trace(go.Scatter(
                    x=df["time"], y=df["vwap"],
                    mode="lines",
                    line=dict(color=T["accent"], width=2.8),
                    name="VWAP",
                    hoverinfo="x+y",
                ), row=1, col=1)
    
            # ── Row 1: VWAP sigma bands (±1σ and ±2σ) ───────────────────
            # Shaded fill between ±1σ gives traders a quick "fair value zone";
            # ±2σ is an institutional extension level (often a mean-revert target).
            if show_overlays:
                _has_bands = all(c in df.columns for c in
                                 ("vwap_upper1", "vwap_lower1", "vwap_upper2", "vwap_lower2"))
                if _has_bands:
                    # ±2σ outer band — very faint fill, thin dashed line
                    fig.add_trace(go.Scatter(
                        x=pd.concat([df["time"], df["time"][::-1]]),
                        y=pd.concat([df["vwap_upper2"], df["vwap_lower2"][::-1]]),
                        fill="toself",
                        fillcolor="rgba(100,160,255,0.04)",
                        line=dict(color="rgba(100,160,255,0.0)"),
                        name="VWAP ±2σ",
                        showlegend=True,
                        hoverinfo="skip",
                    ), row=1, col=1)
                    # ±1σ inner band — slightly more visible
                    fig.add_trace(go.Scatter(
                        x=pd.concat([df["time"], df["time"][::-1]]),
                        y=pd.concat([df["vwap_upper1"], df["vwap_lower1"][::-1]]),
                        fill="toself",
                        fillcolor="rgba(100,160,255,0.08)",
                        line=dict(color="rgba(100,160,255,0.0)"),
                        name="VWAP ±1σ",
                        showlegend=True,
                        hoverinfo="skip",
                    ), row=1, col=1)
                    # Upper band lines
                    for _bname, _bcol, _bdash, _bclr in [
                        ("VWAP +2σ", "vwap_upper2", "dot",   "rgba(100,160,255,0.50)"),
                        ("VWAP +1σ", "vwap_upper1", "dash",  "rgba(100,160,255,0.70)"),
                        ("VWAP -1σ", "vwap_lower1", "dash",  "rgba(100,160,255,0.70)"),
                        ("VWAP -2σ", "vwap_lower2", "dot",   "rgba(100,160,255,0.50)"),
                    ]:
                        fig.add_trace(go.Scatter(
                            x=df["time"], y=df[_bcol],
                            mode="lines",
                            line=dict(color=_bclr, width=0.9, dash=_bdash),
                            name=_bname,
                            hoverinfo="x+y",
                        ), row=1, col=1)
    
            # ── Row 1: ORB range — prominent zone shading + bold labeled lines ─
            # The ORB zone is the primary decision region. It gets:
            #   • Amber filled rect (the consolidation range)
            #   • Thick solid green/red horizontal borders (the breakout trigger levels)
            #   • Right-side bold price labels (font-size 10, always readable)
            #   • Centered "◆ ORB ZONE" watermark inside the band
            _or_inf = _get_or(df)
            _orh    = _or_inf["high"] if _or_inf else None
            _orl    = _or_inf["low"]  if _or_inf else None
            if show_overlays and _orh is not None and _orl is not None:
                # Amber zone fill — very low opacity so candles remain readable
                fig.add_hrect(y0=_orl, y1=_orh,
                              fillcolor="rgba(255,193,7,0.07)",
                              line=dict(color="rgba(255,193,7,0.30)", width=1),
                              row=1, col=1)
                # ORB HIGH — solid green line, right label
                fig.add_hline(
                    y=_orh,
                    line_color="rgba(0,200,60,0.95)",
                    line_dash="solid", line_width=1.2,
                    annotation_text=f"<b>ORB HIGH  ${_orh:.2f}</b>",
                    annotation_font_color="rgba(0,155,50,1)",
                    annotation_font_size=10,
                    annotation_position="right",
                    row=1, col=1,
                )
                # ORB LOW — solid red line, right label
                fig.add_hline(
                    y=_orl,
                    line_color="rgba(220,53,69,0.95)",
                    line_dash="solid", line_width=1.2,
                    annotation_text=f"<b>ORB LOW  ${_orl:.2f}</b>",
                    annotation_font_color="rgba(190,40,40,1)",
                    annotation_font_size=10,
                    annotation_position="right",
                    row=1, col=1,
                )
                # "◆ ORB ZONE" watermark anchored inside the band (left side)
                _orb_mid = (_orh + _orl) / 2
                fig.add_annotation(
                    x=df["time"].iloc[max(0, len(df) // 6)],
                    y=_orb_mid,
                    text="<b>◆ ORB ZONE</b>",
                    showarrow=False,
                    font=dict(color="rgba(165,115,0,0.70)", size=9, family="Arial Black"),
                    xanchor="left", yanchor="middle",
                    row=1, col=1,
                )
    
            # ── Row 1: TP / SL zones ───────────────────────────────────────
            # FIX: For REAL trades, _ep_show/_sl_show/_tp_show/_tr_show are on
            # the OPTION-PREMIUM scale (~$3-7), but row 1's y-axis is the
            # UNDERLYING stock price (~$685-765). Drawing premium-scale hlines
            # on that axis previously produced a giant inverted hrect (the
            # "pink rectangle" bug) spanning from ~$4.50 to the chart's low.
            # _levels_on_chart_scale is only True for SIM/ghost trades, where
            # entry_price IS the underlying price. Real-trade Entry/SL/TP/Trail
            # remain visible (correctly, in premium terms) on the right panel.
            if show_overlays and show_lvls and _ep_show is not None and _levels_on_chart_scale:
                _ph   = float(df["high"].max())
                _pl   = float(df["low"].min())
                _rng  = max(_ph - _pl, 0.01)
                _tp_c = min(_tp_show, _ph + _rng * 0.30)
                _sl_c = max(_sl_show, _pl - _rng * 0.30)
                _ep_c = _ep_show
                _tr_c = _tr_show if (_tr_show and _tr_show > _sl_c) else None
                fig.add_hrect(y0=_ep_c, y1=_tp_c,
                              fillcolor="rgba(26,127,55,.08)", line_width=0,
                              row=1, col=1)
                fig.add_hrect(y0=_sl_c, y1=_ep_c,
                              fillcolor="rgba(207,34,46,.08)", line_width=0,
                              row=1, col=1)
                for _y, _clr, _dsh, _lbl in [
                    (_tp_c, T["green"],  "dot",  f"TP ${_tp_show:.3f}"),
                    (_sl_c, T["red"],    "dot",  f"SL ${_sl_show:.3f}"),
                    (_ep_c, T["yellow"], "dash", f"Entry ${_ep_c:.3f}"),
                ]:
                    fig.add_hline(y=_y, line_color=_clr, line_dash=_dsh, line_width=1.5,
                                  annotation_text=_lbl, annotation_font_color=_clr,
                                  annotation_font_size=9, annotation_position="right",
                                  row=1, col=1)
                if _tr_c:
                    fig.add_hline(y=_tr_c, line_color=T["purple"],
                                  line_dash="longdash", line_width=1,
                                  annotation_text=f"Trail ${_tr_c:.3f}",
                                  annotation_font_color=T["purple"],
                                  annotation_font_size=9, annotation_position="right",
                                  row=1, col=1)
    
            # ── Row 1: Entry / Exit markers from today's DB trades ──────────
            # BUY  : hollow circle (#56CCF2) — light-blue ring, transparent fill
            # SELL : filled circle (#BB6BD9) — pink/purple, closed trades only
            # Both carry rich Plotly hover tooltips via customdata + hovertemplate.
            # Only drawn when show_overlays=True (Simulation Mode checkbox checked).
            _BUY_COL  = "#56CCF2"   # light blue  — entry
            _SELL_COL = "#BB6BD9"   # pink/purple — exit
            _today_s  = date.today().isoformat()
    
            # FIX: BUY/SELL circles for REAL trades were previously gated behind
            # `show_overlays` (the "🎓 Simulation Mode" checkbox) — so a real
            # trade entered with Simulation Mode OFF never got an entry circle
            # at all. Real-trade markers should always render; only SIM_ ghost
            # trades are tied to the Simulation Mode toggle.
            for _t in (today_trades or []):
                # ── Date guard ────────────────────────────────────────────────
                # SIM_ contracts always use yesterday's bar timestamps — skip the
                # wall-clock date check for them.  For live trades, only render
                # markers whose entry_time matches today so stale fills don't
                # bleed onto today's chart.
                _et_raw  = str(_t.get("entry_time") or "")
                _is_sim  = str(_t.get("contract_symbol", "")).startswith("SIM_")
                if _is_sim and not show_overlays:
                    continue   # ghost/sim markers only show with Simulation Mode on
                if not _et_raw:
                    continue
                try:
                    _et_parsed  = pd.to_datetime(_et_raw)
                    # Normalize to tz-naive ET so subtraction against df["time"]
                    # (which is always tz-naive) doesn't raise TypeError.
                    # DB stores tz-naive ET strings via _to_et_isoformat(); older rows
                    # or Alpaca fill timestamps may carry a UTC-offset (+/-HH:MM).
                    if _et_parsed.tzinfo is not None:
                        _et_parsed = _et_parsed.tz_convert("America/New_York").tz_localize(None)
                    _entry_date = _et_parsed.date().isoformat()
                except Exception:
                    continue
                if not _is_sim and _entry_date != _today_s:
                    continue
    
                try:
                    _et   = _et_parsed
                    _ep_t = float(_t.get("entry_price") or 0)
                    if _ep_t <= 0:
                        continue    # skip malformed / zero-price entries
    
                    # ── BUY hover data ────────────────────────────────────────
                    _strat_id  = str(_t.get("strategy_id") or "INST_ORB")
                    _risk_cap  = 50.0   # 1% of $5k starting capital
                    # Contracts: capital at risk / (option price × 30% stop × 100 multiplier)
                    # Simplified to per-share: $50 / (price × 0.30)
                    _contracts = max(1, int(_risk_cap / max(_ep_t * 0.30, 0.01)))
                    _opt_type  = str(_t.get("option_type") or "").upper() or "CALL"
                    _strike    = float(_t.get("strike") or round(_ep_t))
                    _is_sim_t  = str(_t.get("contract_symbol", "")).startswith("SIM_")
                    # Option premium: Black-Scholes for sim trades, actual fill for real trades
                    if _is_sim_t:
                        _cached_opt = _t.get("opt_entry_px")   # set by sim engine
                        if _cached_opt:
                            _opt_entry_px_v = float(_cached_opt)
                        else:
                            # DB trade: recompute from stored entry_time
                            _opt_entry_px_v = _bs_price(_ep_t, _strike, _et_parsed.to_pydatetime(),
                                                        _opt_type == "CALL")
                        _opt_entry = f"${_opt_entry_px_v:.2f}"
                    else:
                        _opt_entry_px_v = _ep_t   # real fill — entry_price IS the option price
                        _opt_entry = f"${_opt_entry_px_v:.2f}"
    
                    # ── Underlying price for chart placement ───────────────────
                    # FIX: Row 1's y-axis is the UNDERLYING stock price (~$700-750).
                    # For SIM trades, entry_price IS already on that scale — use it
                    # directly. For REAL trades, entry_price is the OPTION PREMIUM
                    # (~$3-7), so plotting the BUY circle at y=_ep_t placed it far
                    # below the visible chart, making it invisible. Look up the
                    # underlying close price at entry_time from this chart's own
                    # OHLC data (df) instead.
                    if _is_sim_t:
                        _underlying_entry = _ep_t
                    else:
                        _underlying_entry = _ep_t   # fallback if lookup fails
                        try:
                            _idx_e = (df["time"] - _et).abs().idxmin()
                            _underlying_entry = float(df.loc[_idx_e, "close"])
                        except Exception:
                            pass
    
                    # ── Entry: HOLLOW light-blue circle — visually dominant ────
                    # Two-layer approach: a white halo ring underneath the blue
                    # ring creates a "selected" look that stands out from the tiny
                    # arrowhead markers used by the swing-structure annotations.
                    # Halo layer (white filled circle, rendered first = below)
                    fig.add_trace(go.Scatter(
                        x=[_et], y=[_underlying_entry],
                        mode="markers",
                        marker=dict(
                            symbol="circle",
                            size=24,
                            color="white",
                            line=dict(color="white", width=0),
                            opacity=0.85,
                        ),
                        name="_buy_halo",
                        showlegend=False,
                        hoverinfo="skip",
                    ), row=1, col=1)
                    # BUY ring layer (top)
                    fig.add_trace(go.Scatter(
                        x=[_et], y=[_underlying_entry],
                        mode="markers+text",
                        marker=dict(
                            symbol="circle-open",   # hollow — entry indicator
                            size=22,
                            color=_BUY_COL,
                            line=dict(color=_BUY_COL, width=3),
                        ),
                        text=[f"BUY ${_ep_t:.2f}"],
                        textposition="bottom center",
                        textfont=dict(color=_BUY_COL, size=9, family="Arial"),
                        name="BUY",
                        showlegend=True,
                        legendgroup="trades",
                        customdata=[[_strat_id, _contracts, _underlying_entry, _risk_cap,
                                     _opt_entry, _opt_type, _strike]],
                        hovertemplate=(
                            "<b style='color:#56CCF2'>● BUY</b><br>"
                            "Strategy: <b>%{customdata[0]}</b><br>"
                            "Contracts: <b>%{customdata[1]}</b><br>"
                            "Underlying: <b>$%{customdata[2]:.2f}</b><br>"
                            "Option: <b>%{customdata[5]} $%{customdata[6]:.0f} | %{customdata[4]}</b><br>"
                            "Initial Risk: <b>~$%{customdata[3]:.0f}</b>"
                            "<extra></extra>"
                        ),
                    ), row=1, col=1)
    
                    # ── Exit: filled circle — ONLY for closed trades ──────────
                    # Open positions get no SELL circle; don't imply an exit
                    # that hasn't happened.
                    _xt_raw = str(_t.get("exit_time") or "")
                    _xp_raw = _t.get("exit_price")
                    _has_exit = (
                        bool(_xt_raw)
                        and len(_xt_raw) > 5
                        and _xt_raw not in ("None", "nan", "")
                        and _xp_raw not in (None, 0, 0.0, "0", "0.0", "None")
                    )
                    _pnl     = float(_t.get("realized_pnl") or 0.0)
                    _pnl_str = f"+${_pnl:.0f}" if _pnl >= 0 else f"-${abs(_pnl):.0f}"
    
                    if _has_exit:
                        _xt = pd.to_datetime(_xt_raw)
                        # Same tz-naive normalization as entry time — exit timestamps
                        # from Alpaca fills may carry a UTC offset.
                        if _xt.tzinfo is not None:
                            _xt = _xt.tz_convert("America/New_York").tz_localize(None)
                        _xp = float(_xp_raw)
    
                        # ── Underlying price for chart placement ───────────────
                        # Same fix as the BUY marker: for REAL trades, exit_price
                        # is the OPTION PREMIUM, not the underlying price that
                        # row 1's y-axis uses. Look up the underlying close at
                        # exit_time from this chart's OHLC data (df).
                        if _is_sim_t:
                            _underlying_exit = _xp
                        else:
                            _underlying_exit = _xp   # fallback if lookup fails
                            try:
                                _idx_x = (df["time"] - _xt).abs().idxmin()
                                _underlying_exit = float(df.loc[_idx_x, "close"])
                            except Exception:
                                pass
    
                        # ── SELL hover data ───────────────────────────────────
                        _exit_reason = str(
                            _t.get("exit_reason") or
                            _t.get("close_reason") or
                            ("TP hit" if _pnl > 0 else "SL hit" if _pnl < 0 else "manual")
                        )
                        # ── Option exit price (BS for sim, actual fill for real) ──
                        if _is_sim_t:
                            _cached_exit_opt = _t.get("opt_exit_px")
                            if _cached_exit_opt:
                                _opt_exit_px_v = float(_cached_exit_opt)
                            else:
                                _xt_parsed_dt = pd.to_datetime(_xt_raw).to_pydatetime()
                                _opt_exit_px_v = _bs_price(_xp, _strike, _xt_parsed_dt,
                                                           _opt_type == "CALL")
                            _opt_exit = f"${_opt_exit_px_v:.2f}"
                        else:
                            _opt_exit_px_v = _xp      # real fill — exit_price IS option price
                            _opt_exit = f"${_opt_exit_px_v:.2f}"
    
                        # ── P&L % — based on option premium change, not underlying ──
                        # Underlying moves 0.1–1%; option premium moves 20–100%.
                        # Showing underlying % makes it look like the trade barely moved.
                        if _opt_entry_px_v > 0:
                            _pnl_pct = ((_opt_exit_px_v - _opt_entry_px_v) / _opt_entry_px_v * 100)
                        else:
                            _pnl_pct = 0.0
                        _pnl_abs_str = f"{abs(_pnl_pct):.1f}%"
                        _pnl_pct_str = (f"PROFIT {_pnl_abs_str}" if _pnl_pct >= 0
                                        else f"LOSS {_pnl_abs_str}")
                        _pnl_net_str = f"+${_pnl:.2f}" if _pnl >= 0 else f"-${abs(_pnl):.2f}"
    
                        # ── Exit: filled circle — visually dominant ───────────
                        # White halo ring underneath the filled circle creates
                        # the same "selected" separation from swing annotations.
                        # Halo layer
                        fig.add_trace(go.Scatter(
                            x=[_xt], y=[_underlying_exit],
                            mode="markers",
                            marker=dict(
                                symbol="circle",
                                size=28,
                                color="white",
                                line=dict(color="white", width=0),
                                opacity=0.85,
                            ),
                            name="_sell_halo",
                            showlegend=False,
                            hoverinfo="skip",
                        ), row=1, col=1)
                        # SELL fill layer (top)
                        fig.add_trace(go.Scatter(
                            x=[_xt], y=[_underlying_exit],
                            mode="markers+text",
                            marker=dict(
                                symbol="circle",
                                size=22,
                                color=_SELL_COL,
                                line=dict(color="white", width=3),
                            ),
                            text=[f"SELL {_pnl_str}"],
                            textposition="top center",
                            textfont=dict(color=_SELL_COL, size=9, family="Arial"),
                            name="SELL",
                            showlegend=False,
                            legendgroup="trades",
                            customdata=[[_exit_reason, _underlying_exit, _pnl_pct_str, _pnl_net_str,
                                         _opt_exit, _opt_entry]],
                            hovertemplate=(
                                "<b style='color:#BB6BD9'>● SELL</b><br>"
                                "Exit Type: <b>%{customdata[0]}</b><br>"
                                "Underlying: <b>$%{customdata[1]:.2f}</b><br>"
                                "Option Entry: <b>%{customdata[5]}</b> → Exit: <b>%{customdata[4]}</b><br>"
                                "P&L %%: <b>%{customdata[2]}</b><br>"
                                "Net P&L: <b>%{customdata[3]}</b>"
                                "<extra></extra>"
                            ),
                        ), row=1, col=1)
    
                        # Dashed connector: green = profit, red = loss
                        _path_col = "#1a7f37" if _pnl >= 0 else "#cf222e"
                        fig.add_shape(
                            type="line",
                            x0=_et, x1=_xt,
                            y0=_underlying_entry, y1=_underlying_exit,
                            line=dict(color=_path_col, width=1.8, dash="dash"),
                            row=1, col=1,
                        )
                    # Open positions: entry circle only, no exit circle.
    
                except Exception as _me:
                    logger.debug("Trade marker render error: %s", _me)
                    continue    # malformed row — skip silently
    
            # ── Row 2: Volume bars (green = bullish candle, red = bearish) ─
            _vcols = [
                "rgba(26,127,55,.75)" if c >= o else "rgba(207,34,46,.75)"
                for c, o in zip(df["close"], df["open"])
            ]
            # Gold highlight for breakout candle (highest RVOL, ≥ 2.0×)
            if "rvol" in df.columns and not df["rvol"].empty:
                _rvol_max_idx = int(df["rvol"].idxmax())
                if float(df["rvol"].iloc[_rvol_max_idx]) >= 2.0:
                    _vcols[_rvol_max_idx] = "rgba(255,215,0,.95)"
    
            fig.add_trace(go.Bar(
                x=df["time"], y=df["volume"],
                marker_color=_vcols, marker_line_width=0,
                name="Volume",
                hoverinfo="x+y",   # participates in x unified tooltip
            ), row=2, col=1)
    
            # 10-bar rolling average + 200% gate — only when overlays are on
            if show_overlays:
                _avg_vol = df["volume"].rolling(10, min_periods=1).mean()
                fig.add_trace(go.Scatter(
                    x=df["time"], y=_avg_vol,
                    mode="lines",
                    line=dict(color="rgba(255,165,0,.65)", width=1.3, dash="dot"),
                    name="Avg Vol",
                    hoverinfo="x+y",
                ), row=2, col=1)
                _avg_last = float(_avg_vol.iloc[-1]) if not _avg_vol.empty else 0.0
                if _avg_last > 0:
                    fig.add_hline(
                        y=_avg_last * 2.0,
                        line_color="rgba(0,210,80,.80)",
                        line_dash="dot", line_width=1.8,
                        annotation_text="200% gate",
                        annotation_font_color="rgba(0,180,60,1)",
                        annotation_font_size=8,
                        annotation_position="right",
                        row=2, col=1,
                    )
    
            # ── Axis + layout ──────────────────────────────────────────────
            fig.update_layout(
                **_base_layout,
                height=300 if compact else 520,
                margin=dict(t=16, b=24, l=0, r=110),
                bargap=0.06,
            )
            fig.update_xaxes(type="date", rangeslider=dict(visible=False),
                             gridcolor="rgba(0,0,0,0.06)",
                             tickfont=dict(size=9, color="black", family="Arial"),
                             showticklabels=False, row=1, col=1)
            fig.update_xaxes(type="date",
                             gridcolor="rgba(0,0,0,0.06)",
                             tickfont=dict(size=9, color="black", family="Arial"),
                             showticklabels=True, row=2, col=1)
            fig.update_yaxes(tickprefix="$", gridcolor="rgba(0,0,0,0.06)",
                             tickfont=dict(size=9, color="black", family="Arial"),
                             autorange=True, title=None, row=1, col=1)
            fig.update_yaxes(gridcolor="rgba(0,0,0,0.06)",
                             tickfont=dict(size=8, color="black", family="Arial"),
                             title=None, tickformat=",.0f", row=2, col=1)
    
            # ── Institutional structure overlays (swing labels, trendlines, Fib) ─
            # Added after axis config so structure annotations go on the price row.
            if show_overlays:
                fig = _add_structure_overlays(fig, df)
    
            return fig
    
        def _render_orb_chart(df: pd.DataFrame, label: str,
                              show_lvls: bool = False,
                              chart_title: str = "",
                              today_trades: list = None,
                              show_overlays: bool = True,
                              compact: bool = False,
                              signal_pill: str = "") -> None:
            # Guard + render the combined ORB chart.
            # show_overlays driven by Simulation Mode checkbox:
            #   True  → VWAP, EMA9/21, ORB zone, TP/SL, BUY/SELL markers
            #   False → clean chart: base candlesticks + volume bars only
            # Emit ticker label + optional signal pill as a single HTML row above
            # the chart — keeps title and signal in one element with no gaps.
            if chart_title or signal_pill:
                _title_html = (
                    f"<span style='font-size:.72rem;font-weight:200;color:#111827;"
                    f"font-family:Arial Black,Arial,sans-serif;line-height:3'>"
                    f"{chart_title}</span>" if chart_title else ""
                )
                _pill_html = (
                    f"<span style='font-size:.50rem;font-weight:700;letter-spacing:.07em;"
                    f"text-transform:uppercase;white-space:nowrap'>{signal_pill}</span>"
                    if signal_pill else ""
                )
                st.markdown(
                    f"<div style='display:flex;align-items:center;"
                    f"justify-content:space-between;padding:2px 4px;"
                    f"margin-bottom:-10px;line-height:1.2'>"
                    f"{_title_html}{_pill_html}</div>",
                    unsafe_allow_html=True,
                )
            if df is None or df.empty or len(df) < 2:
                st.error(
                    f"⚠️ No bar data for {label}. "
                    "IEX feed doesn't carry ETFs (SPY/QQQ) — yfinance fallback also "
                    "unavailable. Check internet connection or Alpaca API key."
                )
                return
            st.plotly_chart(
                _apply_contrast(
                    _orb_live_fig(df, show_lvls=show_lvls,
                                  chart_title=chart_title,
                                  today_trades=today_trades or [],
                                  show_overlays=show_overlays,
                                  compact=compact)
                ),
                use_container_width=True,
                # scrollZoom lets the user pinch/scroll to zoom in and out.
                # We keep the mode bar visible but strip clutter — only zoom,
                # pan, reset-axes, and the hover tools remain.
                config={
                    "scrollZoom": True,
                    "displayModeBar": True,
                    "modeBarButtonsToRemove": [
                        "toImage", "sendDataToCloud", "select2d",
                        "lasso2d", "toggleSpikelines", "hoverClosestCartesian",
                        "hoverCompareCartesian",
                    ],
                    "displaylogo": False,
                },
            )
    
        # ── Chart container header + legend ───────────────────────────────
        # Always show the bar date so users know which session they're viewing.
        # When market is closed the bars are from the last completed session
        # (yesterday) — making this explicit prevents confusion.
        try:
            _bar_date_str = df_5m["time"].iloc[-1].strftime("%b %-d, %Y")
        except Exception:
            _bar_date_str = _session_date_lbl
        _is_today = (_bar_date_str and date.today().strftime("%b %-d, %Y") == _bar_date_str)
        _session_tag = (
            f" · {_bar_date_str} ← last completed session"
            if (not _session_is_live and not _is_today) else
            f" · {_bar_date_str}"
        )
        _legend_html = (
            '<div class="legend">'
            f'<span class="leg"><span class="leg-line" style="background:{T["yellow"]}"></span>Entry</span>'
            f'<span class="leg"><span class="leg-line" style="background:{T["green"]}"></span>TP</span>'
            f'<span class="leg"><span class="leg-line" style="background:{T["red"]}"></span>SL</span>'
            f'<span class="leg"><span class="leg-line" style="background:{T["purple"]}"></span>Trail</span>'
            f'<span class="leg"><span class="leg-line" style="background:{T["accent"]}"></span>VWAP</span>'
            f'<span class="leg"><span class="leg-line" style="background:rgba(0,220,70,.8)"></span>OR High</span>'
            f'<span class="leg"><span class="leg-line" style="background:rgba(255,82,82,.8)"></span>OR Low</span>'
            f'<span class="leg"><span class="leg-line" style="background:rgba(0,210,80,.8)"></span>200% Vol</span>'
            '</div>'
        )
        st.markdown(_legend_html, unsafe_allow_html=True)
    
        # ── Load today's closed trades for BUY/SELL chart markers ───────────
        # ── Trade marker loading: strict mode separation ─────────────────────
        # SIM mode  → only show trades with contract_symbol LIKE 'SIM_%'
        #             (written by the sim engine in this file)
        # LIVE mode → only show trades WITHOUT the 'SIM_' prefix
        #             (real paper/live trades placed by the bot loop)
        #
        # This prevents old paper trades from bleeding onto the sim chart and
        # sim trades from polluting the live chart — the single most common
        # cause of "wrong time / wrong price" marker confusion.
        # Load today's real broker/paper fills for BUY/SELL chart markers.
        # sim_mode is an overlay toggle — trade data always comes from the live DB.
        # FIX: _tk MUST be defined before it's used in the _today_trades filter
        # below. It was previously assigned several lines further down (under
        # "Compose chart titles"), so every reference to it here raised
        # NameError — silently caught by the bare `except Exception: pass`,
        # leaving _today_trades permanently [] and NO entry/exit circles ever
        # drawn on the chart, regardless of the y-axis-scale fix applied
        # earlier. Moving the assignment up here fixes this.
        # _tk drives chart titles and trade-marker filtering.
        # Use chart_ticker (user override) for 1m/5m; fall back to bot ticker.
        _ct_now = st.session_state.get("chart_ticker")
        _tk = (_ct_now if _ct_now and _ct_now != "—"
               else (_ticker if _ticker and _ticker != "—" else "—"))
    
        _today_str  = date.today().isoformat()
        _all_trades_today: list = []
        try:
            _all_trades_raw   = get_all_trades(limit=200)
            _all_trades_today = [
                t for t in _all_trades_raw
                if str(t.get("entry_time", "")).startswith(_today_str)
            ]
        except Exception:
            pass
    
        def _trades_for_ticker(sym: str) -> list:
            """Filter today's trades to a specific underlying ticker."""
            return [
                t for t in _all_trades_today
                if str(t.get("underlying_symbol") or t.get("ticker") or "").upper() == sym.upper()
            ]
    
        _today_trades = _trades_for_ticker(_tk)
    
        # ── Compose chart titles — always embed the active ticker symbol ────
    
        if tf_sel == "Quad (4 Charts)":
            # ── 2×2 quad layout: top-4 Power-5 tickers, each showing 5m ─────
            # Tickers are pulled LIVE from scanner_state.json so the quad always
            # mirrors exactly what the bot's scanner is ranking right now.
            # Falls back to the full TICKER_UNIVERSE (SPY→TSLA) if scanner hasn't
            # run yet (e.g. pre-market before first scan completes).
            try:
                from scanner import get_watchlist as _get_scan_wl
                _quad_wl = _get_scan_wl()   # reads scanner_state.json
            except Exception:
                _quad_wl = ["SPY", "QQQ", "AAPL", "NVDA", "TSLA"]
            # Fill to 4 slots; deduplicate while preserving order
            _seen: set = set()
            _quad_tickers: list = []
            for _qt in _quad_wl:
                if _qt not in _seen:
                    _seen.add(_qt)
                    _quad_tickers.append(_qt)
                if len(_quad_tickers) == 4:
                    break
            # Pad with fallbacks if watchlist has fewer than 4 tickers
            for _fb in ["SPY", "QQQ", "AAPL", "NVDA"]:
                if len(_quad_tickers) < 4 and _fb not in _quad_tickers:
                    _quad_tickers.append(_fb)
    
            _qc1, _qc2 = st.columns(2, gap="small")
            for _qi, _qtk in enumerate(_quad_tickers):
                _col = _qc1 if _qi % 2 == 0 else _qc2
                with _col:
                    try:
                        _qdf_raw, _ = _load_sim_bars(_qtk, "5Min")
                        _qdf = _add_indicators(_qdf_raw.copy())
                    except Exception:
                        _qdf = df_5m   # fallback to active ticker on fetch error
                    # Compute signal pill inline so it merges into the chart title row
                    _q_trades = _trades_for_ticker(_qtk)
                    _q_pill = ""
                    try:
                        _q_sigs, _q_bc, _q_ov = _compute_signals(_qdf)
                        _q_ovc = (T["green"] if _q_bc >= 3 else
                                  T["red"]   if _q_bc <= 1 else T["muted"])
                        _q_label = ("CALL" if _q_bc >= 3 else
                                    "PUT"  if _q_bc <= 1 else "NEUTRAL")
                        # Per-signal colored chips with hover tooltips
                        # title= gives native browser tooltip on hover with full detail
                        _qsnames = ["ORB", "VW", "σ", "VOL", "EMA"]
                        _qdots = ""
                        for _qi, (_qico, _qnm, _qdt) in enumerate(_q_sigs):
                            _qdc = ("#16a34a" if _qico == "🟢" else
                                    "#dc2626" if _qico == "🔴" else "#9ca3af")
                            _qsl  = _qsnames[_qi] if _qi < len(_qsnames) else _qnm[:3]
                            # Tooltip: signal name + detail on hover
                            _qtip = f"{_qnm}: {_qdt}".replace("'", "&#39;")
                            _qdots += (
                                f"<span title='{_qtip}' style='background:{_qdc};color:#fff;"
                                f"font-size:.52rem;font-weight:600;padding:1px 5px;"
                                f"border-radius:3px;letter-spacing:.05em;"
                                f"margin-right:3px;display:inline-block;cursor:help'>{_qsl}</span>"
                            )
                        _q_bg = ("#16a34a" if _q_bc >= 3 else
                                 "#dc2626" if _q_bc <= 1 else "#6b7280")
                        _q_pill = (
                            f"<span style='background:{_q_bg}22;color:{_q_ovc};"
                            f"font-size:.52rem;font-weight:400;padding:1px 6px;"
                            f"border-radius:4px;border:1px solid {_q_bg}55;"
                            f"letter-spacing:.3em'>{_q_label}</span>"
                            f"&ensp;{_qdots}"
                        )
                    except Exception:
                        pass
                    _render_orb_chart(
                        _qdf, "5m", show_lvls=(_qtk.upper() == _tk.upper()),
                        chart_title=f"{_qtk} · 5m{_session_tag}",
                        today_trades=_q_trades,
                        show_overlays=sim_mode, compact=True,
                        signal_pill=_q_pill,
                    )
        else:
            _chart_title = (
                f"{_tk} · 5m{_session_tag}"
                if tf_sel == "5m Chart" else
                f"{_tk} · 1m{_session_tag}"
            )
            _render_orb_chart(df_display, tf_sel, show_lvls=_show_levels,
                              chart_title=_chart_title,
                              today_trades=_today_trades,
                              show_overlays=sim_mode)
    
        # ── Audit log — collapsible expander + live fragment refresh ─────────
        # The function is defined with @st.fragment so it refreshes independently
        # every 15 s.  We CALL it inside st.expander so the user can collapse the
        # feed to focus on the chart without losing the data.
        @st.fragment(run_every=15)
        def _live_audit_log():
            """
            Emoji card feed — rerenders every 15 s independently of the full page.
            Merges bar_eval (candle narration) + all other system events into one
            chronological list, newest first.  Each card is color-coded by emoji:
              🟢 green border  — trade executions, fills, P&L
              🟡 yellow border — scanning, watching, candle observations
              🔴 red border    — errors, API failures, risk gates
            No Module column, no message truncation, no raw tracebacks.
            """
            import pytz as _audit_tz
            from log_explanations import tag_for_message
    
            def _fmt_ts(raw: str) -> str:
                """Convert stored UTC timestamp to Eastern HH:MM:SS."""
                try:
                    _u = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").replace(
                        tzinfo=_audit_tz.utc)
                    return _u.astimezone(
                        _audit_tz.timezone("America/New_York")).strftime("%H:%M:%S")
                except Exception:
                    return raw[:8] if raw else "—"
    
            def _card_color(msg: str, level: str) -> tuple[str, str]:
                """
                Return (border_hex, bg_hex) based on the leading emoji or level.
                Priority: emoji prefix > log level.
                """
                _lvl = level.upper() if level else ""
                if msg.startswith("🟢"):
                    return "#2ea043", "rgba(46,160,67,0.07)"
                if msg.startswith("🔴") or "ERR" in _lvl or "CRIT" in _lvl:
                    return "#cf222e", "rgba(207,34,46,0.07)"
                # 🟡 or anything else → yellow/neutral
                return "#b08800", "rgba(176,136,0,0.07)"
    
            # ── Synthetic "what's happening right now" status card ─────────────
            # Recomputed fresh on every 15 s fragment tick (independent of the
            # outer page's variables, which may be stale between full reruns).
            # Tells the user in plain language whether the trading engine is
            # CURRENTLY alive (bot_state.json updated in the last 2 min) and
            # whether the market is open — and what to click, if anything.
            # Pinned to the top of the feed so it's always the first thing seen,
            # without adding any new page-level UI elements/space.
            _bot_now   = _read_bot_state()
            _alive_now = _bot_engine_alive(_bot_now.get("last_update"))
            _mkt_now   = _bot_now.get("market_open", False)
            _now_ts    = datetime.now(_audit_tz.timezone("America/New_York")).strftime("%H:%M:%S")
    
            # Only build a status card when something needs attention (bot stopped/error).
            # When bot is running normally, skip the card — it just creates noise.
            _status_card = None
            if not _alive_now and _mkt_now:
                _s_bdr, _s_bg, _s_dot = "#cf222e", "rgba(207,34,46,0.07)", "🔴"
                _s_msg = (f"Bot does not appear to be running (no update since "
                          f"{_bot_now.get('last_update') or 'never'}). Market is open — "
                          "click ▶ Start in the sidebar, or relaunch CeloTrader.command.")
                _status_card = (
                    f'<div style="display:flex;align-items:flex-start;gap:10px;'
                    f'padding:9px 14px;margin-bottom:4px;border-radius:7px;'
                    f'border-left:3px solid {_s_bdr};background:{_s_bg};'
                    f'font-size:13px;line-height:1.5;">'
                    f'<span style="font-size:14px;margin-top:2px;flex-shrink:0">{_s_dot}</span>'
                    f'<span style="flex:1;color:#000000"><b>Bot status:</b> {_s_msg}</span>'
                    f'<span style="white-space:nowrap;font-size:11px;'
                    f'color:#6e7681;margin-left:8px;padding-top:2px">{_now_ts}</span>'
                    f'</div>'
                )
            elif not _alive_now and not _mkt_now:
                _s_bdr, _s_bg, _s_dot = "#b08800", "rgba(176,136,0,0.07)", "🟡"
                _s_msg = (f"Bot does not appear to be running (no update since "
                          f"{_bot_now.get('last_update') or 'never'}). Market is closed "
                          "too, so nothing's being missed — click ▶ Start (or relaunch "
                          "CeloTrader.command) before the next session opens.")
                _status_card = (
                    f'<div style="display:flex;align-items:flex-start;gap:10px;'
                    f'padding:9px 14px;margin-bottom:4px;border-radius:7px;'
                    f'border-left:3px solid {_s_bdr};background:{_s_bg};'
                    f'font-size:13px;line-height:1.5;">'
                    f'<span style="font-size:14px;margin-top:2px;flex-shrink:0">{_s_dot}</span>'
                    f'<span style="flex:1;color:#000000"><b>Bot status:</b> {_s_msg}</span>'
                    f'<span style="white-space:nowrap;font-size:11px;'
                    f'color:#6e7681;margin-left:8px;padding-top:2px">{_now_ts}</span>'
                    f'</div>'
                )
    
            try:
                with get_conn() as _lconn:
                    # Fetch bar_eval + system events together, sorted newest first
                    _rows = _lconn.execute(
                        "SELECT datetime(ts) as ts, level, component, message "
                        "FROM system_events "
                        "WHERE message NOT LIKE '%403 Client Error%' "
                        "  AND message NOT LIKE '%Forbidden%' "
                        "  AND message NOT LIKE '%429 Client Error%' "
                        "  AND message NOT LIKE '%Too Many Requests%' "
                        "ORDER BY id DESC LIMIT 30"
                    ).fetchall()
    
                if not _rows:
                    if _status_card:
                        st.markdown(_status_card, unsafe_allow_html=True)
                    st.caption("⏳ Waiting for first candle close… (bot must be running)")
                    return
    
                # Build HTML card list — status card only prepended when bot has an issue
                _cards: list[str] = ([_status_card] if _status_card else [])
                for _r in _rows:
                    _ts  = _fmt_ts(_r["ts"])
                    _msg = str(_r["message"])
                    _lvl = str(_r["level"] or "")
                    _bdr, _bg = _card_color(_msg, _lvl)
    
                    # Strip leading emoji from the message body for cleaner display
                    _body = _msg
                    for _pfx in ("🟢 ", "🟡 ", "🔴 "):
                        if _body.startswith(_pfx):
                            _body = _body[len(_pfx):]
                            break
    
                    # Determine display emoji
                    if _msg.startswith("🟢"):
                        _dot = "🟢"
                    elif _msg.startswith("🔴") or "ERR" in _lvl.upper() or "CRIT" in _lvl.upper():
                        _dot = "🔴"
                    else:
                        _dot = "🟡"
    
                    # Look up the keyword tag (if any) for this message so users can
                    # cross-reference "Playbooks → 9 · Trading Log Explanations" for
                    # a plain-English breakdown of what the line means.
                    _tag = tag_for_message(_msg)
                    _tag_badge = (
                        f'<span style="white-space:nowrap;font-size:10px;font-weight:700;'
                        f'font-family:monospace;color:{_bdr};border:1px solid {_bdr};'
                        f'border-radius:4px;padding:1px 6px;margin-left:8px;'
                        f'background:{_bg}">{_tag}</span>'
                        if _tag else ""
                    )
    
                    _cards.append(
                        f'<div style="'
                        f'display:flex;align-items:flex-start;gap:10px;'
                        f'padding:9px 14px;margin-bottom:4px;border-radius:7px;'
                        f'border-left:3px solid {_bdr};background:{_bg};'
                        f'font-size:13px;line-height:1.5;'
                        f'">'
                        f'<span style="font-size:14px;margin-top:2px;flex-shrink:0">{_dot}</span>'
                        f'<span style="flex:1;color:#000000">{_body}</span>'
                        f'{_tag_badge}'
                        f'<span style="white-space:nowrap;font-size:11px;'
                        f'color:#6e7681;margin-left:8px;padding-top:2px">{_ts}</span>'
                        f'</div>'
                    )
    
                _feed_html = (
                    '<div style="'
                    'max-height:340px;overflow-y:auto;'
                    'padding:6px 2px;'
                    '">'
                    + "".join(_cards)
                    + "</div>"
                )
                st.markdown(_feed_html, unsafe_allow_html=True)
    
            except Exception as _ex:
                st.caption(f"🔴 Log feed error: {type(_ex).__name__} — {_ex}")
    
        # Call inside expander so the feed is collapsible without losing the
        # @st.fragment auto-refresh — Streamlit keeps fragments alive inside expanders.
        with st.expander("💭 Live Thought Process — Bot Decision Log", expanded=True):
            _live_audit_log()
    
    # ── Right column: full position panel HTML ────────────────────────────────
    with col_pos:
        # ── Risk Budget + Max Premium — single compact inline strip ──────────
        _rbudget_cls = "c-red" if _risk_budget < 5 else ""
        st.markdown(f"""
    <div style="display:flex;gap:6px;margin-bottom:5px">
      <div class="mc" style="flex:1;padding:5px 8px">
    <div class="ml" style="font-size:.5rem">Risk Budget</div>
    <div class="mv {_rbudget_cls}" style="font-size:.82rem">${_risk_budget:,.2f}</div>
    <div class="md" style="font-size:.48rem">30% stop</div>
      </div>
      <div class="mc" style="flex:1;padding:5px 8px">
    <div class="ml" style="font-size:.5rem">Max Premium</div>
    <div class="{_afford_cls}" style="font-size:.82rem">${_max_afford:,.2f}</div>
    <div class="md" style="font-size:.48rem">cap/contract</div>
      </div>
    </div>
    """, unsafe_allow_html=True)
        _panel_title = "Open Position" if open_trade else "No Position"
        _opt_type    = open_trade["option_type"].upper() if open_trade else ("CALL" if _bull_count >= 3 else "PUT")
        _contract    = open_trade["contract_symbol"] if open_trade else "— (sim)"
        _sub_line    = (f"{open_trade['ticker']} · {_opt_type} · {open_trade['contracts']} contracts"
                        if open_trade else f"Simulation · {_opt_type} bias")
        _badge_cls   = "b-call" if _opt_type == "CALL" else "b-put"
    
        # ── Price levels and P&L block ────────────────────────────────────
        if _show_levels:
            _pnl_bg  = "rgba(26,127,55,.08)"  if _pnl_unr >= 0 else "rgba(207,34,46,.08)"
            _pnl_bdr = "rgba(26,127,55,.2)"   if _pnl_unr >= 0 else "rgba(207,34,46,.2)"
            _pnl_col = T["green"]              if _pnl_unr >= 0 else T["red"]
            _cur_delta_pct = (_cur_px_show - _ep_show) / _ep_show * 100 if _ep_show else 0
            # When the market is closed, _cur_opt_px is the LAST KNOWN premium
            # (persisted in bot_state.json), not a live quote — label it as such
            # so the user doesn't mistake it for a real-time price.
            _cur_lbl = "Current" if (_mkt_open or _levels_on_chart_scale) else "Current (last known)"
            _price_rows = [
                ("Entry",    f"${_ep_show:.3f}",     T["yellow"]),
                (_cur_lbl,   f"${_cur_px_show:.3f}", T["accent"]),
                ("Stop-loss",   f"${_sl_show:.3f}",  T["red"]),
                ("Take-profit", f"${_tp_show:.3f}",  T["green"]),
            ]
            if _tr_show:
                _price_rows.append(("Trail stop", f"${_tr_show:.3f}", T["purple"]))
            _price_html = "".join(
                f'<div class="prow"><span class="pk">{k}</span>'
                f'<span class="pv" style="color:{c}">{v}</span></div>'
                for k, v, c in _price_rows
            )
            _pnl_box_html = f"""
    <div class="pnl-box" style="background:{_pnl_bg};border:1px solid {_pnl_bdr};margin:8px 0">
      <div class="pnl-lbl" style="color:{_pnl_col}">Unrealised P&amp;L</div>
      <div class="pnl-num" style="color:{_pnl_col}">{'+' if _pnl_unr>=0 else ''}${_pnl_unr:.2f}</div>
    </div>
    <div class="prog-head"><span>SL ${_sl_show:.3f}</span><span>TP ${_tp_show:.3f}</span></div>
    <div class="prog-track">
      <div class="prog-fill" style="width:{_prog_v:.0f}%;background:{T['green']}"></div>
    </div>"""
        else:
            _price_html   = f'<div class="prow"><span class="pk">Current</span><span class="pv c-acc">${_cur_px:.3f}</span></div>'
            _pnl_box_html = f'<div style="font-size:.63rem;color:{T["muted"]};padding:6px 0">No active position.</div>'
    
        # ── Signal basis rows (ORB engine — RSI/MACD removed) ────────────
        _orb_lbl = (
            "Above OR High" if _orb_dir == "bullish" else
            "Below OR Low"  if _orb_dir == "bearish" else
            "Inside range"  if _or_high else "Pending"
        )
        # Plain-English labels — no jargon acronyms in the sidebar badges
        _sb_data = [
            ("Range Break",   _orb_lbl,                                  # ORB → Range Break
             "b-bull" if _orb_dir == "bullish" else
             "b-bear" if _orb_dir == "bearish" else "b-man"),
            ("Rel. Volume",   f"{_vol_ratio:.1f}× normal",               # RVOL → Rel. Volume
             "b-bull" if _vol_ratio >= 2.0 else
             "b-man"  if _vol_ratio >= 1.2 else "b-bear"),
            ("Avg Price Lvl", "Above avg" if _above_vwap else "Below avg",  # VWAP → Avg Price Level
             "b-bull" if _above_vwap else "b-bear"),
            ("Trend Line",    "Up (fast>slow)" if _ema_bull else "Down (fast<slow)",  # EMA → Trend Line
             "b-bull" if _ema_bull else "b-bear"),
            ("Bot Bias",      _overall.replace("🟢 ","").replace("🔴 ","").replace("⚪ ",""),  # Overall → Bot Bias
             "b-bull" if _bull_count >= 3 else
             "b-bear" if _bull_count <= 1 else "b-man"),
        ]
        _sig_html = "".join(
            f'<div class="sig-row"><span class="sig-k">{k}</span>'
            f'<span class="badge {bc}">{v}</span></div>'
            for k, v, bc in _sb_data
        )
    
        # ── Position panel (rendered when there's an open trade) ─────────────
        if _show_levels:
            # ── Position panel ────────────────────────────────────────────────────
            st.markdown(f"""
    <div class="pos-panel">
      <div class="pos-head">
    <span class="pos-ht">{_panel_title}</span>
    <span class="badge {_badge_cls}">{_opt_type}</span>
      </div>
      <div class="pos-body">
    <div class="pos-sym">{_contract}</div>
    <div class="pos-sub">{_sub_line}</div>
    <div class="pos-divider"></div>
    {_price_html}
    {_pnl_box_html}
    <div class="pos-divider"></div>
    <div class="sig-section">Signal Basis</div>
    {_sig_html}
    <div class="pos-divider"></div>
      </div>
    </div>
    """, unsafe_allow_html=True)
    
        # ── Multi-position summary (NEW — MAX_CONCURRENT_POSITIONS) ───────────
        # The position panel above shows only ONE position (the most recently
        # opened, via get_open_trade()). When a 2nd position is also open,
        # show a compact extra row for EACH open trade so neither leg is
        # invisible. Sourced from bot_state.json's per-trade "open_positions"
        # dict (written every tick by _manage_open_position).
        _all_open_trades_live = get_open_trades()
        if len(_all_open_trades_live) > 1:
            _open_positions_live = bot.get("open_positions") or {}
            _mp_rows = []
            for _t in _all_open_trades_live:
                _pdata      = _open_positions_live.get(str(_t["id"]), {})
                _p_opt_type = (_t.get("option_type") or "").upper()
                _p_badge    = "b-call" if _p_opt_type == "CALL" else "b-put"
                _p_entry    = float(_t.get("entry_price", 0))
                _p_cur      = _pdata.get("current_option_price")
                if _p_cur and _p_cur > 0:
                    _p_pnl     = (_p_cur - _p_entry) * _t.get("contracts", 1) * 100
                    _p_cur_str = f"${_p_cur:.3f}"
                    _p_pnl_str = f"{'+' if _p_pnl >= 0 else ''}${_p_pnl:.2f}"
                    _p_pnl_col = T["green"] if _p_pnl >= 0 else T["red"]
                else:
                    _p_cur_str = f"${_p_entry:.3f} (entry)"
                    _p_pnl_str = "+$0.00"
                    _p_pnl_col = T["muted"]
                _p_stage = "Stage 2 (BE)" if _pdata.get("stage1_done") else "Stage 1"
                _mp_rows.append(
                    f'<div style="display:flex;justify-content:space-between;align-items:center;'
                    f'padding:6px 4px;border-bottom:1px solid {T["border"]};font-size:.62rem;gap:6px">'
                    f'<span><span class="badge {_p_badge}">{_p_opt_type}</span>&nbsp;'
                    f'<b>{_t.get("ticker","")}</b> · {str(_t.get("contract_symbol",""))[:18]}</span>'
                    f'<span style="color:{T["muted"]}">Entry ${_p_entry:.3f} → {_p_cur_str} · {_p_stage}</span>'
                    f'<span style="color:{_p_pnl_col};font-weight:700">{_p_pnl_str}</span>'
                    f'</div>'
                )
            st.markdown(
                f'<div style="margin-bottom:10px">'
                f'<div style="font-size:.56rem;font-weight:700;color:{T["muted"]};'
                f'text-transform:uppercase;letter-spacing:.1em;margin-bottom:4px">'
                f'Open Positions ({len(_all_open_trades_live)}/{MAX_CONCURRENT_POSITIONS})</div>'
                + "".join(_mp_rows) +
                '</div>',
                unsafe_allow_html=True,
            )
    
        # ── Action buttons ────────────────────────────────────────────────────
        # Ghost trade feature removed — use the Trade Journal Close buttons
        # for manual position management.
        if not sim_mode and open_trade:
            if st.button("📤 Close Position", use_container_width=True):
                manual_close_position()
                st.success("Close order sent")
                st.rerun()
    
        # ── Sim controls ─────────────────────────────────────────────────────
        st.markdown("<hr style='margin:6px 0;border-color:#d0d7de'>",
                    unsafe_allow_html=True)
        # Spacer + padding so checkbox doesn't touch the panel edge
        st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
        _prev_sim = st.session_state.get("sim_mode", True)
        st.checkbox("🎓 Simulation Mode", key="sim_mode")
        _new_sim  = st.session_state.get("sim_mode", True)
        if _new_sim != _prev_sim:
            # Mode toggled: purge sim trade cache and reset engine state so no
            # sim data persists when switching to live mode (or vice versa).
            st.session_state.pop("sim_trades", None)
            st.session_state.pop("sim_state",  None)
            reset_session_state()
            # Force dashboard to re-read the correct DB on the next render cycle
            st.rerun()
    
        # ── Bot Eval Log ──────────────────────────────────────────────────────
        # Accumulates contract evaluations this session (newest first, last 8).
        # Each entry shows: Ticker · CALL/PUT · contracts · entry price · expiry · max profit
        if "bot_eval_log" not in st.session_state:
            st.session_state["bot_eval_log"] = []
    
        if _last_eval_ticker and _last_eval_time and _last_eval_eff_entry:
            _prev = st.session_state["bot_eval_log"]
            _is_new = (
                not _prev
                or _prev[0].get("time") != _last_eval_time
                or _prev[0].get("ticker") != _last_eval_ticker
            )
            if _is_new:
                # Derive contracts from risk budget (mirrors risk.py formula):
                #   risk_per_contract = eff_entry * ORB_STOP_PCT(0.30) * 100
                #   n_contracts = floor(risk_budget / risk_per_contract)
                _stop_pct = 0.30
                _rpc = _last_eval_eff_entry * _stop_pct * 100
                _n_c = max(1, int(_risk_budget / _rpc)) if (_rpc > 0 and _risk_budget > 0) else 1
                # Stage-1 target = 50% gain on option premium
                _exp_profit = _last_eval_eff_entry * 0.50 * _n_c * 100
                _expiry_raw = bot.get("last_eval_expiry") or ""
                # Format expiry: same-day → "0DTE", otherwise "MMM D"
                try:
                    from datetime import datetime as _dt, date as _date
                    _exp_date = _dt.strptime(_expiry_raw, "%Y-%m-%d").date()
                    _expiry_lbl = "0DTE" if _exp_date == _date.today() else _exp_date.strftime("%b %-d")
                except Exception:
                    _expiry_lbl = _expiry_raw or "—"
                # Format strike: omit decimals if whole number
                _strike_raw = _last_eval_strike
                try:
                    _strike_val = float(_strike_raw)
                    _strike_lbl = f"${_strike_val:.0f}" if _strike_val == int(_strike_val) else f"${_strike_val:.2f}"
                except Exception:
                    _strike_lbl = f"${_strike_raw}" if _strike_raw else "—"
                st.session_state["bot_eval_log"].insert(0, {
                    "time":     _last_eval_time,
                    "ticker":   _last_eval_ticker,
                    "opt_type": _last_eval_opt,
                    "contracts": _n_c,
                    "entry":    _last_eval_eff_entry,
                    "expiry":   _expiry_lbl,
                    "strike":   _strike_lbl,
                    "profit":   _exp_profit,
                })
                st.session_state["bot_eval_log"] = st.session_state["bot_eval_log"][:8]
    
        _eval_entries = st.session_state.get("bot_eval_log", [])
        _t_text   = T["text"]
        _t_border = T["border"]
        _t_green  = T["green"]
        _t_muted  = T["muted"]
        _t_surf2  = T["surface2"]
        _el_rows = ""
        for _e in _eval_entries:
            _e_col = _t_green if _e["opt_type"] == "CALL" else T["red"]
            _el_rows += (
                f"<div style='font-size:.57rem;color:{_t_text};padding:4px 0;"
                f"border-bottom:1px solid {_t_border};line-height:1.4'>"
                f"<b style='color:{_e_col}'>{_e['ticker']} {_e['opt_type']}</b>"
                f" · <b>{_e.get('strike','—')}</b>"
                f" · <b>{_e['contracts']}c</b>"
                f" · In&nbsp;<b>${_e['entry']:.2f}</b>"
                f" · <b>{_e['expiry']}</b>"
                f" · Max&nbsp;<b style='color:{_t_green}'>+${_e['profit']:.0f}</b>"
                f"<span style='float:right;color:{_t_muted};font-size:.50rem'>{_e['time']}</span>"
                f"</div>"
            )
        if not _el_rows:
            _el_rows = (
                f"<div style='font-size:.56rem;color:{_t_muted};padding:4px 0'>"
                f"No contract evaluations yet this session.</div>"
            )
        st.markdown(
            f"<div style='display:flex;flex-direction:column;background:{_t_surf2};"
            f"border:1px solid {_t_border};border-radius:6px;padding:8px 10px;"
            f"margin-top:8px;box-sizing:border-box;width:100%;overflow:hidden'>"
            f"<div style='font-size:.52rem;font-weight:700;color:{_t_muted};"
            f"text-transform:uppercase;letter-spacing:.1em;margin-bottom:4px'>Bot Eval Log</div>"
            + _el_rows + "</div>",
            unsafe_allow_html=True,
        )
    
        # Auto-refresh and Flip-Idle controls removed per user request.
        # Flip trading state is still tracked by the bot engine (bot_state.json)
        # and visible in the topbar strategy pill when a flip fires.
    
    
    # ═══════════════════════════════════════════════════════════════════════════════
    

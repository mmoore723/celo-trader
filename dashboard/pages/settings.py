"""
dashboard/pages/settings.py — Risk Settings page.

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
    """Render the Risk Settings page."""
    st.markdown("# ⚙️  Settings")
    _settings_tab1, _settings_tab2 = st.tabs(["⚙️ Risk & Controls", "🧾 Tax & Savings"])
    
    with _settings_tab1:
        # ── Risk & Controls ─────────────────────────────────────────────────────
        st.caption("Changes apply to the next trade cycle immediately — no restart needed.")
        settings = get_settings()
    
        # Show save-confirmation banner (set by the form submit + st.rerun() below)
        if st.session_state.get("_risk_settings_saved_msg"):
            st.success(st.session_state.pop("_risk_settings_saved_msg"))
    
        # ── ORB Strategy Parameters (read-only reference card) ────────────────────
        st.markdown("#### 🔒 ORB Strategy Parameters")
        st.info(
            "These values are **hard-coded in the ORB engine** and enforce the 1.5× Profit Factor "
            "profile. They are not adjustable from this screen — changes require a code-level audit."
        )
        _orb_params = [
            ("Risk per Trade",        "1% of account equity",             "Positions never risk more than $equity × 0.01"),
            ("Initial Stop-Loss",     "30% of option premium",            "Hard floor on every new position"),
            ("Stop Tightening",       "−5pp every 15 min (floor 10%)",    "0–14 min: 30% · 15–29 min: 25% · 30–44 min: 20%"),
            ("Stage-1 Profit Target", "+50% gain → sell 50% of contracts","Locks in profit, moves remainder to break-even"),
            ("Stage-2 Stop",          "Break-even (entry price)",         "Second tranche never turns into a loss"),
            ("Time-Box",              "45 minutes hard exit",             "Force-exits any open position after 45 min"),
            ("Min R:R Gate",          "1.2 : 1 → 1.6 : 1 (auto, balance-based)",  "Trade blocked if reward/risk < gate after slippage. 1.2 below the bootstrap balance tier, 1.6 once graduated — see Settings"),
            ("Slippage Buffer",       "5% both sides",                    "Entry priced at ask × 1.05; exits at bid × 0.95"),
            ("Max Notional Cap",      "20% of equity in premium",                "Prevents outsized exposure on cheap options"),
            ("Trades per Session",    "Unlimited (no per-session cap)",          "8 strategies; bot re-enters any time no position is open"),
            ("Flip Trigger",          "Hard stop only (dynamic_stop_Xpct)",      "Break-even, time-box, and manual closes do NOT arm a flip"),
            ("Flip Requirements",     "RVOL ≥ 200% + R:R gate (1.2–1.6) + 1% risk",  "All entry gates enforced on flip — no shortcuts"),
        ]
        orb_html = (
            "<table style='width:100%;border-collapse:collapse;font-size:0.84rem;'>"
            "<thead><tr>"
            "<th style='text-align:left;padding:5px 8px;border-bottom:2px solid #d0d7de;color:#1f2328;'>Parameter</th>"
            "<th style='text-align:left;padding:5px 8px;border-bottom:2px solid #d0d7de;color:#1f2328;'>Value</th>"
            "<th style='text-align:left;padding:5px 8px;border-bottom:2px solid #d0d7de;color:#1f2328;'>Rationale</th>"
            "</tr></thead><tbody>"
        )
        for i, (param, val, why) in enumerate(_orb_params):
            bg = "#f6f8fa" if i % 2 == 0 else "#ffffff"
            orb_html += (
                f"<tr style='background:{bg};'>"
                f"<td style='padding:5px 8px;color:#1f2328;border-bottom:1px solid #eaecef;font-weight:600;'>{param}</td>"
                f"<td style='padding:5px 8px;color:#0969da;border-bottom:1px solid #eaecef;font-weight:700;'>{val}</td>"
                f"<td style='padding:5px 8px;color:#57606a;border-bottom:1px solid #eaecef;font-size:0.78rem;'>{why}</td>"
                f"</tr>"
            )
        orb_html += "</tbody></table>"
        st.markdown(orb_html, unsafe_allow_html=True)
    
        st.markdown("---")
    
        # ── Adjustable Risk Parameters ────────────────────────────────────────────
        with st.form("risk_form"):
            st.markdown("#### 🎛  Adjustable Parameters")
            st.caption("These controls are live — changes take effect on the next trade cycle.")
    
            # ── Risk Per Trade selector ───────────────────────────────────────────
            st.markdown("**Risk Per Trade**")
            _rpt_options = {
                "auto": "🤖 Auto (balance-based tier: 1% / 3% / 5%)",
                0.01:   "1%  — Tier 1 / Conservative",
                0.03:   "3%  — Tier 3 / Growth",
                0.05:   "5%  — Tier 4 / Bootstrap (HIGH RISK ⚠️)",
            }
            _rpt_current = settings.get("risk_per_trade")   # None → auto
            _rpt_default_key = _rpt_current if _rpt_current in _rpt_options else "auto"
            _rpt_index = list(_rpt_options.keys()).index(_rpt_default_key)
    
            _rpt_selected_label = st.radio(
                "Risk per trade override",
                options=list(_rpt_options.values()),
                index=_rpt_index,
                horizontal=True,
                label_visibility="collapsed",
                help=(
                    "Auto: the bot picks the tier based on your balance and growth-mode setting. "
                    "Manual: pins risk to that exact % regardless of balance. "
                    "5% triggers a HIGH RISK WARNING in every log."
                ),
            )
            # Map selected label back to its key (None for auto, float for manual)
            _rpt_key_selected = [k for k, v in _rpt_options.items() if v == _rpt_selected_label][0]
            _rpt_save_value   = None if _rpt_key_selected == "auto" else float(_rpt_key_selected)
    
            if _rpt_save_value == 0.05:
                st.warning(
                    "⚠️ **5% risk selected.** At this level 2 consecutive full stops will fire the "
                    "10% daily kill lock and freeze trading for 24 hours. Proceed with caution."
                )
    
            st.markdown("---")
    
            # ── R:R Threshold Mode selector ───────────────────────────────────────
            st.markdown("**R:R (Reward:Risk) Threshold Mode**")
            _boot_boundary = settings.get("growth_risk_boundary_boot", 5_000.0)
            _rr_options = {
                "auto": (
                    f"🤖 Auto (Small Account 1.2 R:R below ${_boot_boundary:,.0f}, "
                    f"switches to Professional 1.6 R:R at/above)"
                ),
                "small_account": "Small Account (1.2 R:R)",
                "professional":  "Professional Standard (1.6 R:R)",
            }
            _rr_current = settings.get("rr_ratio_mode", "auto")
            _rr_default_key = _rr_current if _rr_current in _rr_options else "auto"
            _rr_index = list(_rr_options.keys()).index(_rr_default_key)
    
            _rr_selected_label = st.radio(
                "R:R threshold mode",
                options=list(_rr_options.values()),
                index=_rr_index,
                horizontal=False,
                label_visibility="collapsed",
                help=(
                    "Controls the minimum reward-to-risk ratio required before a trade "
                    "is allowed (RiskManager.evaluate_rr). With the bot's fixed exit "
                    "parameters, the actual R:R on every setup is ~1.27 — a flat 1.6 "
                    "minimum blocks 100% of trades on a small account. "
                    "Auto (default): uses the relaxed 1.2 R:R gate while your balance "
                    "is below the bootstrap tier boundary, then automatically tightens "
                    "to the 1.6 'Professional Standard' gate once you grow past it. "
                    "Small Account / Professional Standard: pin the gate manually "
                    "regardless of balance."
                ),
            )
            _rr_mode_save_value = [k for k, v in _rr_options.items() if v == _rr_selected_label][0]
    
            if _rr_mode_save_value == "professional":
                st.info(
                    "ℹ️ **Professional Standard (1.6 R:R)** is mathematically unreachable "
                    "with the bot's current fixed exit parameters (~1.27 actual R:R) — "
                    "this will block all entries until exit parameters change."
                )
    
            st.markdown("---")
    
            col_a, col_b = st.columns(2)
            with col_a:
                max_loss_pct = st.slider(
                    "Max Daily Loss (% of account)",
                    min_value=5, max_value=25,
                    value=int(settings.get("max_daily_loss_pct", 0.12) * 100),
                    step=1,
                    help="Trading halts for the rest of the day once session losses exceed this %.",
                ) / 100
            with col_b:
                vol_multiplier = st.slider(
                    "RVOL Threshold Multiplier",
                    min_value=1.5, max_value=4.0,
                    value=float(settings.get("volume_filter_multiplier", 2.0)),
                    step=0.25,
                    help="ORB breakout bar must have this multiple of average volume (default 2.0× = 200%).",
                )
    
            st.markdown("---")
            st.markdown("#### Master Controls")
            st.caption("Every toggle takes effect on the next trade cycle — no restart needed.")
            mc1, mc2 = st.columns(2)
            with mc1:
                trading_enabled = st.toggle(
                    "Trading Enabled",
                    value=settings.get("trading_enabled", True),
                    key="toggle_trading_enabled",
                )
                paper_trading = st.toggle(
                    "Paper Trading Mode",
                    value=settings.get("paper_trading", True),
                    key="toggle_paper_trading",
                    help=(
                        "ON → orders go to Alpaca paper account (paper-api.alpaca.markets). "
                        "OFF → orders go to your live Alpaca account. "
                        "The destination is set by ALPACA_BASE_URL in .env — "
                        "this toggle selects which database file to write to and "
                        "tags all logs with [PAPER]."
                    ),
                )
                mtf_required = st.toggle(
                    "Require MTF Agreement",
                    value=settings.get("require_mtf_agreement", True),
                    key="toggle_mtf",
                )
                flip_trading = st.toggle(
                    "Flip Trading (counter-trend after stop-loss)",
                    value=settings.get("flip_trading_enabled", True),
                    key="toggle_flip",
                    help="When ON: a hard stop-loss arms an immediate opposite-direction ORB entry. "
                         "RVOL ≥ 200%, the active R:R gate (1.2–1.6, see R:R Threshold Mode above), "
                         "and 1% risk still required.",
                )
            with mc2:
                earnings_filter = st.toggle(
                    "Earnings Blackout Filter",
                    value=settings.get("earnings_filter_enabled", True),
                    key="toggle_earnings",
                )
                volume_filter = st.toggle(
                    "Volume Filter",
                    value=settings.get("volume_filter_enabled", True),
                    key="toggle_volume",
                )
                email_alerts = st.toggle(
                    "Email Alerts",
                    value=settings.get("email_alerts_enabled", False),
                    key="toggle_email",
                )
                _cur_plan = settings.get("alpaca_data_plan", "free")
                _plan_is_premium = st.toggle(
                    "Alpaca Premium Data",
                    value=(_cur_plan == "premium"),
                    key="toggle_alpaca_plan",
                    help=(
                        "OFF (default) → Free plan: uses IEX feed (regular session 9:30–4:00 PM only). "
                        "Connection errors and the pre-market warning are silenced — they're expected on free tier.\n\n"
                        "ON → Premium / Unlimited plan: uses SIP consolidated feed (pre-market + "
                        "extended hours included). Requires an Alpaca Data Unlimited subscription."
                    ),
                )
                alpaca_data_plan = "premium" if _plan_is_premium else "free"
            st.markdown("---")
            st.markdown("#### 🧠 Active Strategy Router")
            st.caption(
                "Select which strategies the router evaluates each tick. "
                "INST ORB is the primary signal — FVG and VWAP PB are supplementary. "
                "Changes take effect on the next tick and apply to the simulation too."
            )
            _strat_s = get_settings()  # read current saved state for defaults
            sc1, sc2 = st.columns(2)
            with sc1:
                strat_orb   = st.toggle("INST ORB  (Opening Range Breakout)",
                                        value=_strat_s.get("strategy_orb_enabled",   True),
                                        key="tog_strat_orb",
                                        help="09:30–10:30 breakout · RVOL ≥ 2× · vol_sma20×2 · MSA guard")
                strat_bos   = st.toggle("BOS / MSS  (Break of Structure)",
                                        value=_strat_s.get("strategy_bos_enabled",   True),
                                        key="tog_strat_bos",
                                        help="HH/HL or LH/LL structural shift · RVOL ≥ 1.5×")
                strat_mid   = st.toggle("MID BRK  (Mid-Day Breakdown)",
                                        value=_strat_s.get("strategy_mid_enabled",   True),
                                        key="tog_strat_mid",
                                        help="10:30–13:00 · Price < OR Low + VWAP · LH confirmed · vol_sma20×1.5 · SHORT/PUT")
                strat_tcont = st.toggle("TREND CONT  (LH/HL Re-entry)",
                                        value=_strat_s.get("strategy_tcont_enabled", True),
                                        key="tog_strat_tcont",
                                        help="Re-enters confirmed trend at Lower High (PUT) or Higher Low (CALL) · RVOL ≥ 1.2×")
            with sc2:
                strat_vwap  = st.toggle("VWAP Pullback",
                                        value=_strat_s.get("strategy_vwap_enabled",  True),
                                        key="tog_strat_vwap",
                                        help="Trend-continuation reversion to VWAP · RVOL ≥ 1.5×")
                strat_fvg   = st.toggle("FVG  (Fair Value Gap)",
                                        value=_strat_s.get("strategy_fvg_enabled",   True),
                                        key="tog_strat_fvg",
                                        help="Imbalance / liquidity-void fill · RVOL ≥ 1.5×")
                strat_aft   = st.toggle("AFT REV  (Afternoon Reversal)",
                                        value=_strat_s.get("strategy_aft_enabled",   True),
                                        key="tog_strat_aft",
                                        help="13:00–15:30 · HL confirmed · price > prev SH · vol_sma20×1.2 · LONG")
                strat_chan   = st.toggle("CHAN BREAK  (Channel Trendline Rejection)",
                                        value=_strat_s.get("strategy_chan_enabled",  True),
                                        key="tog_strat_chan",
                                        help="Short at descending channel upper line or long at ascending lower line · RVOL ≥ 1.3×")
    
            submitted = st.form_submit_button("💾 Save Settings", use_container_width=True)
            if submitted:
                # Capture old paper_trading value BEFORE saving so we can detect a mode switch
                _prev_paper = bool(settings.get("paper_trading", True))
    
                save_settings({
                    "risk_per_trade":           _rpt_save_value,   # None = auto; 0.01/0.03/0.05 = pinned
                    "rr_ratio_mode":            _rr_mode_save_value,  # "auto" / "small_account" / "professional"
                    "max_daily_loss_pct":       max_loss_pct,
                    "volume_filter_multiplier": vol_multiplier,
                    "volume_filter_enabled":    volume_filter,
                    "require_mtf_agreement":    mtf_required,
                    "earnings_filter_enabled":  earnings_filter,
                    "email_alerts_enabled":     email_alerts,
                    "trading_enabled":          trading_enabled,
                    "paper_trading":            paper_trading,
                    "alpaca_data_plan":         alpaca_data_plan,
                    "flip_trading_enabled":     flip_trading,
                    # Strategy router enables — persisted so sim + live share the same state
                    "strategy_orb_enabled":     strat_orb,
                    "strategy_bos_enabled":     strat_bos,
                    "strategy_vwap_enabled":    strat_vwap,
                    "strategy_fvg_enabled":     strat_fvg,
                    "strategy_mid_enabled":     strat_mid,
                    "strategy_aft_enabled":     strat_aft,
                    "strategy_tcont_enabled":   strat_tcont,
                    "strategy_chan_enabled":     strat_chan,
                })
    
                # ── Mode-switch: paper ↔ live ─────────────────────────────────
                # When paper_trading changes, the active DB path changes immediately
                # (get_db_path() re-reads settings on every call).  We must:
                #   1. init_db() — create tables in the new DB if this is first use
                #   2. backfill_daily_summaries() — rebuild summary table from any
                #      closed trades already in that DB
                #   3. reset_session_state() — clear LIVE_STATE so no stale open-
                #      trade reference from the old DB bleeds into the new mode
                if bool(paper_trading) != _prev_paper:
                    try:
                        from database import init_db as _init_db, backfill_daily_summaries as _bfill
                        _init_db()      # idempotent — creates tables if not present
                        _bfill()        # sync daily_summary from any existing trades
                    except Exception as _dbe:
                        logger.warning("Mode-switch DB init failed (non-fatal): %s", _dbe)
                    try:
                        from trading_logic import reset_session_state as _rst
                        _rst()          # wipes LIVE_STATE open_trade + session pnl
                    except Exception as _rse:
                        logger.warning("Mode-switch state reset failed (non-fatal): %s", _rse)
                    _mode_label = "Paper" if paper_trading else "LIVE"
                    _rr_display = {"auto": "Auto (1.2 → 1.6)", "small_account": "1.2 (Small Account)", "professional": "1.6 (Professional)"}[_rr_mode_save_value]
                    st.session_state["_risk_settings_saved_msg"] = (
                        f"✅ Switched to **{_mode_label} trading** — database and bot state reset. "
                        f"Risk per trade: **{'Auto (tier-based)' if _rpt_save_value is None else f'{_rpt_save_value*100:.0f}%'}** · "
                        f"R:R threshold: **{_rr_display}**."
                    )
                else:
                    _rpt_display = "Auto (tier-based)" if _rpt_save_value is None else f"{_rpt_save_value*100:.0f}%"
                    _rr_display = {"auto": "Auto (1.2 → 1.6)", "small_account": "1.2 (Small Account)", "professional": "1.6 (Professional)"}[_rr_mode_save_value]
                    # Store success message in session state and rerun so widgets re-render
                    # from the freshly-saved file (prevents radio snapping back to stale index).
                    st.session_state["_risk_settings_saved_msg"] = (
                        f"✅ Settings saved — Risk per trade: **{_rpt_display}** · "
                        f"R:R threshold: **{_rr_display}**. Applied on next trade cycle."
                    )
                st.rerun()
        st.markdown("---")
        st.markdown("#### Current Active Settings")
        st.caption("These are the values the bot is using RIGHT NOW.")
        current = get_settings()
        def yn(key, default=True): return "✅ ON" if current.get(key, default) else "🔴 OFF"
    
        # Resolve the live risk % the same way risk.py does
        _cur_bal      = float(current.get("last_known_balance", 5_000.0) or 5_000.0)
        _cur_rpt_raw  = current.get("risk_per_trade")
        from config import get_risk_tier as _get_rt, _VALID_RISK_OVERRIDES as _VRO
        _cur_live_pct = _get_rt(_cur_bal)   # honours manual override
        if _cur_rpt_raw is not None and float(_cur_rpt_raw) in _VRO:
            _rpt_label = f"**{_cur_live_pct*100:.0f}%** (manual override)"
        else:
            _rpt_label = f"**{_cur_live_pct*100:.0f}%** (auto — balance ${_cur_bal:,.0f})"
    
        # Resolve the live R:R gate the same way risk.py does
        from risk import RiskManager as _RM
        _cur_min_rr   = _RM(account_balance=_cur_bal).effective_min_rr()
        _cur_rr_mode  = current.get("rr_ratio_mode", "auto")
        _rr_mode_disp = {"auto": "auto", "small_account": "pinned: Small Account", "professional": "pinned: Professional"}.get(_cur_rr_mode, "auto")
        _rr_gate_label = f"**{_cur_min_rr:.1f} : 1** ({_rr_mode_disp} — balance ${_cur_bal:,.0f})"
    
        # Highest contract premium the bot can size to >=1 contract right now.
        # Anything priced above this triggers SIZING_ZERO (0 contracts) even
        # if it's well within the max-position-cost cap.
        _cur_risk_budget = round(_cur_bal * _cur_live_pct, 2)
        _cur_max_afford  = _RM(account_balance=_cur_bal).max_affordable_premium()
        _max_afford_label = f"**${_cur_max_afford:,.2f}** (risk budget ${_cur_risk_budget:,.2f} at {_cur_live_pct*100:.0f}%)"
    
        col_cfg1, col_cfg2 = st.columns(2)
        with col_cfg1:
            st.markdown("**Sizing & Risk**")
            rows1 = [
                {"Setting": "Risk per Trade",  "Value": _rpt_label},
                {"Setting": "Initial Stop",    "Value": "30% premium (ORB fixed)"},
                {"Setting": "Max Daily Loss",  "Value": f"{current.get('max_daily_loss_pct', 0.12)*100:.0f}%"},
                {"Setting": "RVOL Threshold",  "Value": f"{current.get('volume_filter_multiplier', 2.0):.2f}× avg volume"},
                {"Setting": "Min R:R Gate",    "Value": _rr_gate_label},
                {"Setting": "Max Affordable Premium", "Value": _max_afford_label},
                {"Setting": "Slippage Buffer", "Value": "5% both sides (ORB fixed)"},
                {"Setting": "Time-Box",        "Value": "45 min (ORB fixed)"},
            ]
            st.markdown(_html_table(rows1), unsafe_allow_html=True)
        with col_cfg2:
            st.markdown("**Controls & Toggles**")
            rows2 = [
                {"Setting": "Trading",         "Value": yn("trading_enabled")},
                {"Setting": "Paper Mode",      "Value": "🟡 Paper" if current.get("paper_trading", True) else "🔴 LIVE"},
                {"Setting": "MTF Agreement",   "Value": yn("require_mtf_agreement")},
                {"Setting": "Earnings Filter", "Value": yn("earnings_filter_enabled")},
                {"Setting": "Volume Filter",   "Value": yn("volume_filter_enabled")},
                {"Setting": "Flip Trading",    "Value": yn("flip_trading_enabled")},
                {"Setting": "Email Alerts",    "Value": yn("email_alerts_enabled", False)},
                {"Setting": "Last Balance",    "Value": f"${current.get('last_known_balance', 0):,.2f}"},
                {"Setting": "INST ORB",        "Value": yn("strategy_orb_enabled")},
                {"Setting": "BOS / MSS",       "Value": yn("strategy_bos_enabled")},
                {"Setting": "VWAP PB",         "Value": yn("strategy_vwap_enabled")},
                {"Setting": "FVG",             "Value": yn("strategy_fvg_enabled")},
                {"Setting": "MID BRK",         "Value": yn("strategy_mid_enabled")},
                {"Setting": "AFT REV",         "Value": yn("strategy_aft_enabled")},
                {"Setting": "TREND CONT",      "Value": yn("strategy_tcont_enabled")},
                {"Setting": "CHAN BREAK",       "Value": yn("strategy_chan_enabled")},
            ]
            st.markdown(_html_table(rows2), unsafe_allow_html=True)
    
        # ── Live Flip Trade Status ─────────────────────────────────────────────────
        st.markdown("---")
        st.markdown("#### 🔄 Flip Trade Status")
        st.caption("Live state from the running bot — refreshes on every page reload.")
        _bs = _read_bot_state()
        _flip_eligible       = _bs.get("flip_eligible", False)
        _flip_direction      = _bs.get("flip_direction") or "—"
        _last_direction      = _bs.get("last_direction") or "—"
        _last_closed_raw     = _bs.get("last_trade_closed_time")
        _flip_enabled_cfg    = get_settings().get("flip_trading_enabled", True)
    
        # Format last-closed timestamp
        if _last_closed_raw:
            try:
                from datetime import timezone as _tz
                _dt = datetime.fromisoformat(_last_closed_raw)
                _last_closed_str = _dt.strftime("%Y-%m-%d %H:%M UTC")
            except Exception:
                _last_closed_str = _last_closed_raw
        else:
            _last_closed_str = "—"
    
        _flip_arm_label  = "🟢 ARMED" if _flip_eligible else "⚪ Idle"
        _flip_dir_label  = _flip_direction.capitalize() if _flip_eligible else "—"
    
        _flip_rows = [
            {"Field": "Flip Trading Config",    "Value": "✅ Enabled" if _flip_enabled_cfg else "🔴 Disabled"},
            {"Field": "Flip Slot Status",       "Value": _flip_arm_label},
            {"Field": "Required Flip Direction","Value": _flip_dir_label},
            {"Field": "Last Trade Direction",   "Value": _last_direction.capitalize() if _last_direction != "—" else "—"},
            {"Field": "Last Trade Closed",      "Value": _last_closed_str},
        ]
        st.markdown(_html_table(_flip_rows), unsafe_allow_html=True)
    
        if _flip_eligible and _flip_enabled_cfg:
            st.info(
                f"⚡ Flip slot is **ARMED** — next {_flip_direction.upper()} signal meeting "
                f"RVOL ≥ 200% and the active R:R gate will trigger a flip entry.",
                icon="🔄",
            )
        elif _flip_eligible and not _flip_enabled_cfg:
            st.warning(
                "⚠️ A flip was armed after a stop-loss, but **Flip Trading is disabled** in settings. "
                "The flip slot will be cleared at market close.",
            )
    
    with _settings_tab2:
        # ── Tax & Savings ─────────────────────────────────────────────────────────
        st.markdown("# 🧾  Tax & Savings")
        st.caption(
            "ORB Strategy · two-stage exit · auto-reserve on every winning trade · "
            "Section 1256 rules apply to index options (SPY/QQQ)"
        )
        st.caption(
            "Not financial or tax advice. Consult a CPA before making tax decisions. "
            "These calculations use 2024 federal brackets and top marginal state rates."
        )
    
        # ── ORB Strategy Tax Context ──────────────────────────────────────────────
        with st.expander("📋 ORB Tax Primer — what you need to know before you trade", expanded=False):
            _t1, _t2 = st.columns(2)
            with _t1:
                st.markdown("""
    **Section 1256 Contracts (Index Options — SPY, QQQ, etc.)**
    Options on broad-based indices (SPY, QQQ, IWM, SPX) qualify as Section 1256 contracts under the IRS.
    This means **regardless of how short your hold time is**, the gain is split:
    - **60% treated as long-term capital gain** (max 20% federal rate)
    - **40% treated as short-term capital gain** (ordinary income rates)
    
    This is a **significant tax advantage** for ORB traders — a 45-minute trade on SPY still gets 60% taxed at the lower long-term rate.
    """)
            with _t2:
                st.markdown("""
    **Standard Equity Options (NVDA, TSLA, etc.)**
    Options on individual stocks are NOT Section 1256.
    All gains from trades held under 1 year are **short-term capital gains** — taxed as ordinary income (up to 37%).
    
    **ORB Strategy Implication:**
    - Prioritise SPY/QQQ ORB setups when possible for the 60/40 tax treatment.
    - Individual stock options still generate alpha but face higher tax drag.
    - The bot's top-5 scanner already anchors SPY/QQQ in the watchlist.
    """)
            _tax_settings = get_settings()
            _tier_now = _tax_settings.get("growth_mode", False)
            st.markdown("---")
            st.markdown("**3-Tier Risk → Tax Implications**")
            _tier_rows_tax = [
                {"Risk Tier":    "Tier 3 · 3%",
                 "Balance":      "< $25k",
                 "ORB Win Size": "≈ +2.70% equity/win",
                 "Tax Strategy": "Reinvest 100% — stay below wash-sale threshold"},
                {"Risk Tier":    "Tier 2 · 2%",
                 "Balance":      "$25k – $50k",
                 "ORB Win Size": "≈ +1.80% equity/win",
                 "Tax Strategy": "Reserve ~25-35% of each win — quarterly estimated payments"},
                {"Risk Tier":    "Tier 1 · 1%",
                 "Balance":      "≥ $50k",
                 "ORB Win Size": "≈ +0.90% equity/win",
                 "Tax Strategy": "Auto-sweep active — reserve 25-45% per win (set below)"},
            ]
            st.markdown(_html_table(_tier_rows_tax), unsafe_allow_html=True)
            st.caption("Win size = Tier risk% × 0.90 (stage-1 partial exit math). Full two-stage exit yields slightly more.")
        profile = load_tax_profile()
        ledger  = load_sweep_ledger()
        stats   = get_statistics()
        balance = LIVE_STATE.get("account_balance", STARTING_CAPITAL)
        st.markdown("### Your Tax Profile")
        with st.form("tax_profile_form"):
            col_a, col_b, col_c = st.columns(3)
            with col_a:
                salary = st.number_input(
                    "Annual Salary / W-2 Income ($)",
                    min_value=0, max_value=2_000_000,
                    value=int(profile.get("salary", 0)), step=5000,
                )
            with col_b:
                filing_status = st.selectbox(
                    "Filing Status",
                    options=list(FILING_LABELS.keys()),
                    format_func=lambda x: FILING_LABELS[x],
                    index=list(FILING_LABELS.keys()).index(profile.get("filing_status", "single")),
                )
            with col_c:
                state_options = sorted(STATE_NAMES.keys())
                state = st.selectbox(
                    "State of Residence",
                    options=state_options,
                    format_func=lambda x: f"{x} — {STATE_NAMES[x]}",
                    index=state_options.index(profile.get("state", "TX")),
                )
            col_d, col_e = st.columns(2)
            with col_d:
                ytd_pnl = st.number_input(
                    "YTD Trading Gains Already Realized ($)",
                    min_value=0.0, max_value=1_000_000.0,
                    value=float(profile.get("ytd_trading_pnl", 0.0)), step=100.0,
                )
            with col_e:
                tts = st.toggle(
                    "Trader Tax Status (TTS) elected",
                    value=profile.get("tts_elected", False),
                )
            submitted = st.form_submit_button("💾 Save Tax Profile", use_container_width=True)
            if submitted:
                save_tax_profile({
                    "salary": salary, "filing_status": filing_status,
                    "state": state, "ytd_trading_pnl": ytd_pnl, "tts_elected": tts,
                })
                _saved_tax_info = compute_marginal_rate(salary, filing_status, state, ytd_trading_pnl=ytd_pnl)
                _reserve_pct = min((_saved_tax_info["combined_rate"] + 0.02), 0.45) * 100
                save_settings({"tax_reserve_pct": round(_reserve_pct, 2)})
                profile = load_tax_profile()
                st.success(f"✅ Tax profile saved — {_reserve_pct:.1f}% reserve rate applied.")
        st.markdown("---")
        st.markdown("### Your Exact Tax Rate on Trading Income")
        tax_info = compute_marginal_rate(
            profile.get("salary", 0), profile.get("filing_status", "single"),
            profile.get("state", "TX"), ytd_trading_pnl=profile.get("ytd_trading_pnl", 0.0),
        )
        t1, t2, t3, t4 = st.columns(4)
        with t1:
            st.metric("Federal Bracket", tax_info["federal_bracket"])
        with t2:
            no_tax = "None ✓" if tax_info["no_state_tax"] else f"{tax_info['state_rate']*100:.1f}%"
            st.metric(f"State ({tax_info['state_name']})", no_tax)
        with t3:
            st.metric("Combined Rate", f"{tax_info['combined_pct']}%")
        with t4:
            reserve_pct = min(tax_info["combined_rate"] + 0.02, 0.45) * 100
            st.metric("Auto-Reserve Rate", f"{reserve_pct:.1f}%")
        # ORB-specific example: typical stage-1 exit at a 1% risk, $10k account
        _orb_ex_bal   = balance if balance >= 1000 else 10_000
        _orb_ex_risk  = _orb_ex_bal * 0.01   # 1% risk at current balance
        _orb_ex_win   = _orb_ex_risk * 0.90  # stage-1 exit at +50% on half = ~0.9% of equity
        example_pnl   = max(50.0, round(_orb_ex_win, 2))
        example_reserve = reserve_for_trade(example_pnl, tax_info)
        _is_1256 = LIVE_STATE.get("current_ticker") in {"SPY","QQQ","IWM","DIA","SQQQ","TQQQ","SPX","NDX","RUT"}
        _1256_note = " (Section 1256 — 60/40 long/short split applies)" if _is_1256 else " (individual stock option — short-term rate applies)"
        st.info(
            f"**ORB Example ({int(_orb_ex_bal):,} account · 1% risk):** "
            f"Stage-1 exit wins ≈ ${example_pnl:.0f}{_1256_note} → "
            f"**${example_reserve:.2f} auto-reserved** for taxes → "
            f"**${example_pnl - example_reserve:.2f} yours to keep / reinvest.**"
        )
        if tax_info["no_state_tax"]:
            st.success(f"🎉 {tax_info['state_name']} has no state income tax.")
        st.markdown("---")
        st.markdown("### Tax Reserve Account")
        s1, s2, s3, s4 = st.columns(4)
        with s1:
            st.metric("Total Reserved (YTD)", f"${ledger['total_swept']:,.2f}")
        with s2:
            st.metric("Total Profit (YTD)",   f"${ledger['total_profit']:,.2f}")
        with s3:
            st.metric("Effective Reserve Rate", f"{ledger['effective_rate']}%")
        with s4:
            deadline = next_tax_deadline()
            if deadline:
                color = "🔴" if deadline["urgent"] else "🟡"
                st.metric("Next Estimated Tax Due", f"{deadline['days_away']} days",
                          delta=deadline["label"][:30], delta_color="off")
        if deadline and deadline["urgent"]:
            st.warning(
                f"⚠️ **{deadline['label']}** — {deadline['days_away']} days away. "
                f"You should have **${ledger['total_swept']:,.2f}** ready to pay."
            )
        if ledger.get("entries"):
            st.markdown("#### Recent Auto-Sweeps")
            entries = ledger["entries"][-20:][::-1]
            df_sweep = pd.DataFrame(entries)
            df_sweep["ts"]       = pd.to_datetime(df_sweep["ts"]).dt.strftime("%m/%d %H:%M")
            df_sweep["profit"]   = df_sweep["profit"].map(lambda x: f"${x:,.2f}")
            df_sweep["reserved"] = df_sweep["reserved"].map(lambda x: f"${x:,.2f}")
            df_sweep["rate_pct"] = df_sweep["rate_pct"].map(lambda x: f"{x}%")
            df_sweep = df_sweep.rename(columns={
                "ts": "Time", "trade_id": "Trade ID",
                "profit": "Profit", "reserved": "Reserved", "rate_pct": "Rate",
            })
            st.markdown(_html_table(df_sweep), unsafe_allow_html=True)
        else:
            st.info("No completed profitable trades yet. Sweeps will appear here automatically.")
    
    # ═══════════════════════════════════════════════════════════════════════════════
    

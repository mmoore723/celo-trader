"""
dashboard/sidebar.py — Sidebar navigation and bot controls.

Call render_sidebar() once at the top of dashboard.py.
It sets st.session_state["nav_page"] and returns the active page key.
"""
import streamlit as st
from pathlib import Path

from config import get_settings, save_settings, STARTING_CAPITAL
from trading_logic import LIVE_STATE, run_trading_loop, stop_loop, panic_close_all, reset_session_state
from dashboard.css import T
from dashboard.helpers import _read_bot_state, _bot_engine_alive


def render_sidebar() -> str:
    """Render sidebar nav + bot controls. Returns active page key."""
    # ── Nav session state — initialise before sidebar renders ─────────────────────
    if "nav_page" not in st.session_state:
        st.session_state["nav_page"] = "live"
    
    # ── Sidebar ────────────────────────────────────────────────────────────────────
    with st.sidebar:
        # ── Brand mark — clean light header ──────────────────────────────────────
        # Brand block — combined into ONE st.markdown to avoid extra layout containers
        st.markdown(
            "<div style='text-align:center;padding:10px 4px 0;'>"
            "<div style='font-family:Playfair Display,Georgia,serif;"
            "font-weight:900;font-size:1.1rem;letter-spacing:0.18em;color:#000000;"
            "'>CELO TRADER</div>"
            "<div style='font-size:0.48rem;letter-spacing:0.28em;color:#555555;"
            "text-transform:uppercase;margin-top:2px;margin-bottom:6px;"
            "'>Power 5 · ORB Engine</div>"
            "<hr style='border-color:#cccccc;margin:0 0 8px'/>"
            "</div>",
            unsafe_allow_html=True,
        )
    
        # ── Navigation — full text labels ────────────────────────────────────────
        _NAV = [
            ("🖥  Live Trading",    "live"),
            ("📊  Performance",     "perf"),
            ("📋  Daily Brief",     "brief"),
            ("📓  Trade Journal",   "journal"),
            (None, None),           # section separator
            ("🧪  Backtest",         "backtest"),
            ("📐  Strategy Playbooks", "playbooks"),
            ("⚙️  Settings",        "settings"),
        ]
        _cur_page = st.session_state.get("nav_page", "live")
        # Inject ALL nav active-state CSS in ONE block before the loop.
        # Each st.markdown() call creates a layout container — putting <style>
        # tags inside the loop creates invisible ghost boxes that shift nav items.
        _active_css = "".join(
            f"div[data-testid='stButton']:has(button[data-testid='nav_btn_{_nav_key}']) button"
            f"{{background:#1d4ed8!important;border-color:#1d4ed8!important;"
            f"color:#ffffff!important;font-weight:700!important;}}"
            for _, _nav_key in _NAV
            if _nav_key == _cur_page
        )
        if _active_css:
            st.markdown(f"<style>{_active_css}</style>", unsafe_allow_html=True)
        for _nav_label, _nav_key in _NAV:
            if _nav_label is None:
                # Thin hairline divider only — no text label, no layout gap
                st.markdown(
                    "<hr style='border:none;border-top:1px solid #d0d0d0;"
                    "margin:4px 0'/>",
                    unsafe_allow_html=True,
                )
                continue
            if st.button(
                _nav_label,
                key=f"nav_btn_{_nav_key}",
                use_container_width=True,
            ):
                st.session_state["nav_page"] = _nav_key
                st.rerun()
        st.markdown("<hr style='border-color:#cccccc;margin:10px 0'/>", unsafe_allow_html=True)
        # Live status
        _sidebar_bot = _read_bot_state()
        _sb_mkt_open = _sidebar_bot.get("market_open", False)
        _status  = LIVE_STATE.get("status", "idle")
        # ── Market-closed override: never show RUNNING when market is closed ──────
        if not _sb_mkt_open and _status not in ("idle", "standby", "sim_active"):
            _status = "standby"
        # ── Human-readable status labels ─────────────────────────────────────────
        _STATUS_LABELS = {
            "scanning":  "SCANNING",
            "in_trade":  "IN TRADE",
            "halted":    "HALTED",
            "idle":      "IDLE",
            "standby":   "STANDBY · OUTSIDE WINDOW",
            "sim_active":"SIM ACTIVE",
            "market_closed": "MARKET CLOSED",
            "error":     "ERROR",
        }
        # ── Unrecorded position alert — only error shown in the sidebar ──────────
        # All account metrics (Balance, P&L, Buying Power) live in the top header
        # on the main page. The sidebar is strictly navigation + this alert.
        _ghost = _sidebar_bot.get("ghost_position_alert")
        if _ghost and _ghost.get("positions"):
            _gp = _ghost["positions"][0]
            try:
                _gp_pnl = float(_gp.get("unrealized_pl", 0) or 0)
            except (TypeError, ValueError):
                _gp_pnl = 0.0
            st.error(
                f"🚨 Unrecorded position: {_gp.get('qty')}x {_gp.get('symbol')} "
                f"(P&L ${_gp_pnl:+,.2f}). Check Alpaca's Positions tab.",
                icon="🚨",
            )
        st.markdown("---")
        # ── Bot start / stop ──────────────────────────────────────────────────────
        if "bot_running" not in st.session_state:
            st.session_state["bot_running"] = bool(LIVE_STATE.get("running", False))
        _bot_running_now = st.session_state.get("bot_running", False) or bool(LIVE_STATE.get("running", False))
        if _bot_running_now:
            st.markdown(
                "<style>"
                "div[data-testid='stButton']:has(button[kind='secondary']#btn_start_bot_proxy) button,"
                "button[key='btn_start_bot'] { background:#1a7f37 !important; color:#fff !important; "
                "border-color:#1a7f37 !important; }"
                "</style>",
                unsafe_allow_html=True,
            )
        _bc1, _bc2 = st.columns(2)
        with _bc1:
            _start_lbl = "🟢 Running" if _bot_running_now else "▶ Start"
            if st.button(_start_lbl, key="btn_start_bot", use_container_width=True):
                if not _bot_running_now:
                    import threading as _th
                    # run_trading_loop() itself holds _bot_loop_lock, so if a prior
                    # thread is still winding down the new call returns immediately
                    # with a warning rather than creating a second concurrent loop.
                    _t = _th.Thread(target=run_trading_loop, daemon=True)
                    _t.start()
                    st.session_state["bot_running"] = True
                    st.success("Bot started")
        with _bc2:
            if st.button("⏹ Stop", key="btn_stop_bot",
                         type="primary", use_container_width=True):
                stop_loop()
                st.session_state["bot_running"] = False
                st.info("Stopped")
        # ── PANIC CLOSE ALL — emergency exit for all open positions ──────────────
        st.markdown(
            "<div style='margin:6px 0 2px'></div>",
            unsafe_allow_html=True,
        )
        if st.button(
            "🔴 PANIC — Close All",
            key="sidebar_panic_close",
            use_container_width=True,
            help="Immediately close every open position at market price",
        ):
            try:
                panic_close_all()
                st.success("Panic close sent — check Alpaca for fills.")
            except Exception as _panic_err:
                st.error(f"Panic close error: {_panic_err}")
        st.markdown(
            "<div style='font-size:.56rem;color:#cf222e;text-align:center;"
            "margin-top:2px;margin-bottom:6px'>Emergency: closes all positions at market</div>",
            unsafe_allow_html=True,
        )
        st.caption("⚠️ Running via terminal? These buttons control a separate copy. Restart there instead.")
        st.markdown("---")
        # ── Paper trading toggle ──────────────────────────────────────────────────
        _settings = get_settings()
        _paper = st.toggle(
            "Paper Trading",
            value=_settings.get("paper_trading", True),
            key="toggle_paper",
        )
        if _paper != _settings.get("paper_trading"):
            save_settings({"paper_trading": _paper})
            reset_session_state()
            st.rerun()
        st.caption("🟡 Paper Trading ON → routes to Alpaca paper account")
    
    # ── Read the active page AFTER the sidebar block ──────────────────────────────
    page = st.session_state.get("nav_page", "live")
    # Convenience alias used throughout page bodies
    balance = LIVE_STATE.get("account_balance", STARTING_CAPITAL)
    
    return st.session_state.get("nav_page", "live")

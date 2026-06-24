"""
dashboard.py — Streamlit dashboard for Celo Trader algorithmic options bot.
Pages
─────
1. Live Trading      — real-time chart, position map, RSI, MACD, manual controls
2. Performance       — P&L calendar, equity curve, win rate stats
3. Risk Settings     — adjustable sliders, master controls
4. Trade Journal     — searchable SQLite-backed trade log
5. Backtesting       — historical simulation engine
── Getting Started ──
6. Starting Amounts  — dynamic tier classifier, income projections, comparisons
7. Income Roadmap    — personalised growth curve from live balance
8. Tax & Savings     — bracket calculator, auto-sweep, withdrawal gates
Run with:  streamlit run dashboard.py
"""
import json
import math
import threading
from datetime import datetime, date, timedelta
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import streamlit as st
import streamlit.components.v1 as _st_components   # used for JS auto-refresh
from journal_notes import build_trade_note_html, NOTE_MODAL_CSS  # layman trade-note generator + popup CSS (Trade Journal)

# ── Black-Scholes option pricer ───────────────────────────────────────────────
def _bs_price(S: float, K: float, bar_dt, is_call: bool,
              sigma: float = 0.16, r: float = 0.05) -> float:
    """
    Black-Scholes theoretical option price for a same-day (0DTE-style) contract
    expiring at 16:00 ET.

    Args:
        S       : underlying stock price at the bar (e.g. SPY 530.45)
        K       : strike price (typically round(S))
        bar_dt  : tz-naive ET datetime of the bar (entry or exit)
        is_call : True for CALL, False for PUT
        sigma   : implied vol (0.16 = 16%, typical SPY/QQQ intraday)
        r       : risk-free rate (0.05 = 5%)

    Returns a dollar premium per share (multiply × 100 for per-contract value).
    Falls back to a simple 1.3% approximation on any math error.
    """
    try:
        if isinstance(bar_dt, str):
            bar_dt = datetime.fromisoformat(bar_dt)
        # Time remaining to 16:00 ET expiry in years
        expiry_today = bar_dt.replace(hour=16, minute=0, second=0, microsecond=0)
        t_secs = (expiry_today - bar_dt).total_seconds()
        T = max(t_secs, 60) / (252 * 6.5 * 3600)   # trading-year fraction

        log_SK = math.log(S / K)
        d1 = (log_SK + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)

        def _N(x: float) -> float:
            return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

        disc = math.exp(-r * T)
        call_px = S * _N(d1) - K * disc * _N(d2)
        put_px  = call_px - S + K * disc
        return round(max(0.01, call_px if is_call else put_px), 2)
    except Exception:
        return round(max(0.01, S * 0.013), 2)


# ── MUST be the very first Streamlit call ─────────────────────────────────────
st.set_page_config(
    page_title="Celo Trader",
    page_icon="🔵",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Logging — must be configured before any bot module emits a log line ───────
try:
    from logger_config import setup_logging as _setup_logging
    _setup_logging()
except Exception:
    pass  # logger_config unavailable — bot modules will still work, just unformatted

# ── Import all bot modules ─────────────────────────────────────────────────────
# Do this BEFORE anything that calls get_settings() or references LIVE_STATE.
try:
    from config import get_settings, save_settings, STARTING_CAPITAL, DB_PATH_PAPER, DB_PATH_LIVE
    from database import (
        init_db, get_all_trades, get_daily_summaries,
        get_cumulative_pnl, get_statistics, get_open_trade, get_open_trades, get_conn,
        insert_trade as _db_insert_trade,
    )
    from config import MAX_CONCURRENT_POSITIONS
    from trading_logic import (
        LIVE_STATE, manual_close_position, panic_close_all, close_trade_by_id,
        reset_session_state,
        run_trading_loop, stop_loop,
    )
    from broker import get_clients
    from backtester import Backtester
    from tax_engine import (
        load_tax_profile, save_tax_profile, load_sweep_ledger,
        compute_marginal_rate, profit_advisor, next_tax_deadline,
        STATE_NAMES, FILING_LABELS, reserve_for_trade,
    )
except ImportError as e:
    st.error(f"Import error: {e}. Make sure all bot modules are in the same folder.")
    st.stop()

init_db()


# ── Theme + CSS ───────────────────────────────────────────────────────────────
from dashboard.css import T, inject_css
inject_css()

# ── Shared helpers ────────────────────────────────────────────────────────────
from dashboard.helpers import _read_bot_state, _bot_engine_alive, _BOT_STATE_PATH
from dashboard.helpers import generate_simulation_data, _load_sim_bars, _html_table

# ── Sidebar (sets nav_page in session_state) ──────────────────────────────────
from dashboard.sidebar import render_sidebar
from dashboard.components.price_bar import _price_ticker_bar
from dashboard.components.trade_plan import _generate_trade_plan, _render_trade_plan_banner

page = render_sidebar()
balance = LIVE_STATE.get("account_balance", STARTING_CAPITAL)

# ── Page dispatch ─────────────────────────────────────────────────────────────
from dashboard.pages import (
    live_trading, performance, settings as settings_page,
    daily_brief, trade_journal, backtest, playbooks,
)

if   page == "live":    live_trading.render()
elif page == "perf":    performance.render()
elif page == "settings": settings_page.render()
elif page == "brief":   daily_brief.render()
elif page == "journal": trade_journal.render()
elif page == "backtest": backtest.render()
elif page == "playbooks": playbooks.render()

# ── Price ticker bar (fixed bottom, all pages) ────────────────────────────────
_price_ticker_bar()

"""
dashboard/pages/backtest.py — Backtest page.

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
    """Render the Backtest page."""
    st.markdown("# 🧪  Backtest")
    st.caption(
        "Replay historical 5-min bars through the live ORB strategy rules — "
        "same signal gates, same R:R pre-flight, same two-stage exit. "
        "Options pricing uses Black-Scholes estimates (no free historical chain data available)."
    )
    
    _bt_col1, _bt_col2 = st.columns([2, 1])
    with _bt_col1:
        _bt_ticker = st.selectbox(
            "Ticker",
            ["AAPL", "TSLA", "NVDA", "MSFT", "AMZN", "SPY", "QQQ", "META", "NFLX", "GOOGL"],
            key="bt_ticker",
        )
    with _bt_col2:
        _bt_months = st.selectbox("Look-back", [1, 3, 6, 12], index=1, key="bt_months")
    
    _bt_capital = st.number_input(
        "Starting capital ($)", min_value=500, max_value=100_000,
        value=int(STARTING_CAPITAL), step=500, key="bt_capital",
    )
    
    if st.button("▶  Run Backtest", type="primary", key="bt_run"):
        with st.spinner(f"Replaying {_bt_months} month(s) of {_bt_ticker} bars…"):
            try:
                _bt_alpaca, _ = get_clients()
                _bt = Backtester(
                    alpaca           = _bt_alpaca,
                    ticker           = _bt_ticker,
                    months           = _bt_months,
                    starting_capital = float(_bt_capital),
                )
                _bt_results = _bt.run()
                st.session_state["bt_results"] = _bt_results
                st.session_state["bt_label"]   = f"{_bt_ticker} · {_bt_months}mo · ${_bt_capital:,.0f}"
            except Exception as _bt_err:
                st.error(f"Backtest error: {_bt_err}")
                st.session_state.pop("bt_results", None)
    
    _bt_res = st.session_state.get("bt_results")
    if _bt_res:
        if "error" in _bt_res:
            st.warning(_bt_res["error"])
        else:
            st.markdown(f"**{st.session_state.get('bt_label', '')}**")
            # ── Summary metrics ───────────────────────────────────────────────
            _bm = st.columns(5)
            _bm[0].metric("Total Return", f"{_bt_res.get('total_return_pct', 0):.1f}%")
            _bm[1].metric("Win Rate",     f"{_bt_res.get('win_rate_pct', 0):.1f}%")
            _bm[2].metric("Trades",       _bt_res.get("total_trades", 0))
            _bm[3].metric("Avg Win",      f"${_bt_res.get('avg_win', 0):.2f}")
            _bm[4].metric("Avg Loss",     f"${_bt_res.get('avg_loss', 0):.2f}")
    
            _bm2 = st.columns(4)
            _bm2[0].metric("Sharpe",          f"{_bt_res.get('sharpe', 0):.2f}")
            _bm2[1].metric("Max Drawdown",     f"{_bt_res.get('max_drawdown_pct', 0):.1f}%")
            _bm2[2].metric("Final Balance",    f"${_bt_res.get('final_balance', 0):,.2f}")
            _bm2[3].metric("Stage-1 Hit Rate", f"{_bt_res.get('stage1_rate_pct', 0):.1f}%")
    
            # ── Equity curve ─────────────────────────────────────────────────
            _bt_daily = _bt_res.get("daily_pnl", {})
            if _bt_daily:
                _bt_dates  = sorted(_bt_daily.keys())
                _bt_equity = [float(_bt_capital)]
                for _d in _bt_dates:
                    _bt_equity.append(_bt_equity[-1] + _bt_daily[_d])
                _bt_fig = go.Figure()
                _bt_fig.add_trace(go.Scatter(
                    x=list(range(len(_bt_equity))), y=_bt_equity,
                    mode="lines", name="Equity",
                    line=dict(color="#2563eb", width=2),
                    fill="tozeroy", fillcolor="rgba(37,99,235,0.08)",
                ))
                _bt_fig.update_layout(
                    height=300, margin=dict(l=10, r=10, t=30, b=10),
                    xaxis_title="Trading Day", yaxis_title="Balance ($)",
                    yaxis=dict(tickprefix="$"),
                    plot_bgcolor="white", paper_bgcolor="white",
                )
                st.plotly_chart(_bt_fig, use_container_width=True)
    
            # ── Exit reason breakdown ─────────────────────────────────────────
            _bt_exits = _bt_res.get("exit_reasons", {})
            if _bt_exits:
                st.markdown("**Exit Breakdown**")
                _exit_cols = st.columns(len(_bt_exits))
                for _ei, (_reason, _data) in enumerate(_bt_exits.items()):
                    _exit_cols[_ei].metric(
                        _reason.replace("_", " ").title(),
                        f"{_data['count']} trades",
                        f"${_data['pnl']:.2f}",
                    )
    
            # ── Trade log ────────────────────────────────────────────────────
            _bt_trades = _bt_res.get("trades", [])
            if _bt_trades:
                with st.expander(f"Trade log ({len(_bt_trades)} trades)"):
                    _bt_df = pd.DataFrame(_bt_trades)
                    _show_cols = [c for c in ["date", "option_type", "direction",
                                              "entry_price", "exit_price", "pnl",
                                              "exit_reason", "held_minutes"]
                                  if c in _bt_df.columns]
                    st.dataframe(_bt_df[_show_cols], use_container_width=True)
    
    

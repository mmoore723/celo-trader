"""
dashboard/pages/daily_brief.py — Daily Brief page.

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
    """Render the Daily Brief page."""
    st.markdown(f"""
    <div style="padding:0 0 8px 0;border-bottom:2px solid {T['border']};margin-bottom:14px">
      <span style="font-size:1.4rem;font-weight:800;color:{T['text']};
               font-family:'Syne',sans-serif;letter-spacing:-.015em">📋 Daily Brief</span>
      <span style="font-size:.72rem;color:{T['muted']};font-weight:500;margin-left:10px">
    Today's game plan · generated pre-market
      </span>
    </div>
    """, unsafe_allow_html=True)
    
    _bp_data = st.session_state.get("trade_plan_data")
    if isinstance(_bp_data, dict) and _bp_data:
        # Render one card per ticker that has a plan
        for _bp_ticker, _bp_plan in _bp_data.items():
            if _bp_plan:
                _render_trade_plan_banner(_bp_plan)
    else:
        st.markdown(f"""
    <div style="text-align:center;padding:60px 20px">
      <div style="font-size:2.5rem;margin-bottom:10px">📰</div>
      <div style="font-size:.95rem;font-weight:700;color:{T['text']}">No brief yet today</div>
      <div style="font-size:.78rem;color:{T['muted']};margin-top:5px">
    The daily brief is generated between 09:15–10:00 AM ET.<br>
    Make sure the bot is running during pre-market.
      </div>
    </div>
    """, unsafe_allow_html=True)
    
    # ═══════════════════════════════════════════════════════════════════════════════
    

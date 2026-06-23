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

# ── One-time DB cleanup: purge stale 403 noise from previous sessions ─────────
# This runs once per Streamlit server start (not every rerun) via session_state.
if not st.session_state.get("_403_purged"):
    try:
        with get_conn() as _pc:
            _pc.execute(
                "DELETE FROM system_events "
                "WHERE (message LIKE '%403 Client Error%' OR message LIKE '%Forbidden%') "
                "  AND component = 'broker.alpaca'"
            )
        st.session_state["_403_purged"] = True
    except Exception:
        pass

# ── Theme ──────────────────────────────────────────────────────────────────────
# Read saved theme from settings file first, fall back to light.
# session_state persists within a browser session; settings file persists across restarts.
# Light mode only — no dark mode toggle.
T = {
    "bg": "#f9fafb",      # near-white — avoids harsh pure-white glare
    "surface": "#ffffff",
    "surface2": "#f3f4f6",
    "border": "#e5e7eb",  # Tailwind gray-200 — professional hairline
    "accent": "#2563eb", "green": "#16a34a",
    "red": "#dc2626", "yellow": "#d97706", "text": "#111827",  # near-black
    "muted": "#6b7280", "plot_bg": "#ffffff", "plot_paper": "#f9fafb",
    "purple": "#7c3aed",
}

# ── CSS — stamp hard hex values so Streamlit defaults can't override ──────────
st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&family=Syne:wght@400;600;700;800&family=Playfair+Display:wght@700;900&display=swap');
:root {{
  --t-bg:{T["bg"]};--t-surface:{T["surface"]};--t-border:{T["border"]};
  --t-accent:{T["accent"]};--t-green:{T["green"]};--t-red:{T["red"]};
  --t-yellow:{T["yellow"]};--t-text:{T["text"]};--t-muted:{T["muted"]};
}}
/* ── COCKPIT LAYOUT — full viewport lock, zero padding ────────── */
html, body {{
  height:100vh !important;
  overflow:hidden !important;
  margin:0 !important;
  padding:0 !important;
}}
[data-testid="stAppViewContainer"] {{
  height:100vh !important;
  overflow:hidden !important;
  padding:0 !important;
}}
/* Restore left gutter on the top-level block container so content
   does not clip behind the sidebar border. No overflow:hidden here —
   that was cutting the left edge of text.                          */
.block-container,
[data-testid="stMainBlockContainer"] {{
  padding-top:1rem !important;
  padding-right:0 !important;
  padding-bottom:0 !important;
  padding-left:1rem !important;
  gap:4px !important;
  max-width:100% !important;
}}
[data-testid="stMain"],
[data-testid="stMain"] > div:first-child {{
  padding-top:8px !important;
  padding-right:0 !important;
  padding-bottom:0 !important;
  padding-left:1rem !important;
  margin-left:0 !important;
}}
[data-testid="stVerticalBlock"],
[data-testid="stHorizontalBlock"],
div[data-testid="column"] {{
  padding:0 !important;
  gap:4px !important;
  max-width:100% !important;
}}
/* Hard-cap the top Streamlit toolbar / header banner to 100 px.  */
header[data-testid="stHeader"],
[data-testid="stHeader"] {{
  max-height:100px !important;
  min-height:0 !important;
  height:auto !important;
  padding:0 !important;
  overflow:hidden !important;
}}
/* ── MAIN APP BACKGROUND ──────────────────────────────────────── */
html,body,.stApp,[data-testid="stAppViewContainer"],[data-testid="stMain"],
[data-testid="stMainBlockContainer"],.main .block-container {{
  background-color:{T["bg"]} !important;color:{T["text"]} !important;
}}
html,body,button,input,select,textarea,[class*="css"],.stMarkdown {{
  font-family:'JetBrains Mono',monospace !important;
}}
/* ── Light sidebar ────────────────────────────────────────────────── */
/* overflow:hidden clips the resize-handle drag widget (right:-6px)
   that otherwise bleeds into the main content area and blocks the first
   ~6-10px of text.                                                     */
section[data-testid="stSidebar"] {{
  overflow:hidden !important;
}}
section[data-testid="stSidebar"],section[data-testid="stSidebar"]>div,
section[data-testid="stSidebar"]>div>div {{
  background-color:#F0F2F6 !important;
  border-right:1px solid #cccccc !important;
  /* Strip Streamlit's default sidebar padding so we control spacing */
  padding-top:0 !important;
}}
/* Sidebar inner content container — set explicit padding so items don't touch edges */
section[data-testid="stSidebar"] > div > div:first-child {{
  padding:10px 12px 12px !important;
  gap:0 !important;
}}
section[data-testid="stSidebar"] * {{ color:#000000 !important; }}
section[data-testid="stSidebar"] hr {{ border-color:#cccccc !important; }}
/* Collapse Streamlit's injected vertical gap between sidebar widgets */
section[data-testid="stSidebar"] [data-testid="stVerticalBlock"],
section[data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"] {{
  gap:4px !important;
  row-gap:4px !important;
}}
/* Nav buttons: full-width, white bg, black text, subtle border */
section[data-testid="stSidebar"] .stButton>button {{
  background:#ffffff !important;
  color:#000000 !important;
  border:1px solid #111827 !important;
  border-radius:25px !important;
  font-size:0.82rem !important;
  font-weight:600 !important;
  padding:10px 1px !important;
  width:100% !important;
  text-align:left !important;
  transition:background .12s !important;
  margin-bottom:0 !important;
}}
section[data-testid="stSidebar"] .stButton>button:hover {{
  background:#f0f4ff !important;
  color:#1d4ed8 !important;
  border-color:#1d4ed8 !important;
}}
/* Active page — high-contrast indigo fill with white text */
section[data-testid="stSidebar"] .ct-nav-active button,
section[data-testid="stSidebar"] .stButton>button[aria-pressed="true"] {{
  background:#1d4ed8 !important;
  border-color:#1d4ed8 !important;
  color:#ffffff !important;
  font-weight:700 !important;
}}
h1,h2,h3,h4,.stMarkdown h1,.stMarkdown h2,.stMarkdown h3 {{
  font-family:'Syne',sans-serif !important;color:{T["text"]} !important;letter-spacing:-0.02em;
}}
[data-testid="stMetricValue"] {{
  font-family:'JetBrains Mono',monospace !important;font-size:1.5rem !important;
  font-weight:700 !important;color:{T["text"]} !important;
}}
[data-testid="stMetricLabel"] {{ color:{T["muted"]} !important; }}
/* ── Force all text to pure black for maximum legibility ──────── */
p,h1,h2,h3,h4,h5,h6,li,label,td,th,figcaption,span,
.stMarkdown p,.stMarkdown li,.stMarkdown h1,.stMarkdown h2,
.stMarkdown h3,.stMarkdown h4,.stMarkdown h5,.stMarkdown h6,
.stCaption p,
[data-testid="stCaptionContainer"] p,
[data-testid="stCaptionContainer"] span,
[data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li,
[data-testid="stMarkdownContainer"] span,
[data-testid="stText"] p,
[data-testid="stMetricLabel"],
[data-testid="stMetricValue"],
[data-testid="stMetricDelta"] {{
  color:#000000 !important;
}}
/* SVG text inside Plotly charts */
svg text, .plotly text {{ fill:#000000 !important; color:#000000 !important; }}
/* Expander header: explicit light bg + dark text at all states */
[data-testid="stExpander"] details > summary {{
  background-color:{T["surface"]} !important;
  color:{T["text"]} !important;
}}
[data-testid="stExpander"] details > summary:hover {{
  background-color:{T["bg"]} !important;
  color:{T["text"]} !important;
}}
[data-testid="stExpander"] details > summary p,
[data-testid="stExpander"] details > summary span {{
  color:{T["text"]} !important;
}}
/* ── All input / select / textarea components: white bg, black text ── */
input,select,textarea,
.stTextInput>div>div>input,
.stNumberInput>div>div>input,
.stSelectbox>div>div>div,
[data-baseweb="select"]>div,
[data-baseweb="input"]>div,
[data-baseweb="textarea"]>div {{
  background-color:#ffffff !important;
  color:#000000 !important;
  border:1px solid #aaaaaa !important;
  border-radius:4px !important;
}}
/* Option items inside the dropdown popover */
[data-baseweb="menu"] li,
[data-baseweb="popover"] li,
[role="option"] {{
  background-color:#ffffff !important;
  color:#000000 !important;
}}
[data-baseweb="menu"] li:hover,
[role="option"]:hover {{
  background-color:#f0f2f5 !important;
}}
/* Number-input spin buttons */
.stNumberInput button {{
  background-color:#ffffff !important;
  color:#000000 !important;
  border:1px solid #aaaaaa !important;
}}
.stButton>button:not([kind="primary"]) {{
  background-color:{T["surface"]} !important;color:{T["text"]} !important;
  border:1px solid {T["border"]} !important;
}}
.stButton>button:not([kind="primary"]):hover {{
  border-color:{T["accent"]} !important;color:{T["accent"]} !important;
}}
/* Stop Bot button — always red so it reads as a danger action */
[data-testid="stButton"]:has(button[data-testid="btn_stop_bot"]) button,
div:has(> [data-testid="btn_stop_bot"]) button,
button[key="btn_stop_bot"],
#btn_stop_bot {{
  background-color:{T["red"]} !important;
  color:#ffffff !important;
  border-color:{T["red"]} !important;
  font-weight:700 !important;
}}
/* PANIC CLOSE ALL — sidebar emergency button, red */
[data-testid="stButton"]:has(button[data-testid="sidebar_panic_close"]) button {{
  background-color:#7f0000 !important;
  color:#ffffff !important;
  border-color:#7f0000 !important;
  font-weight:700 !important;
  font-size:0.8rem !important;
  letter-spacing:0.03em !important;
}}
[data-testid="stButton"]:has(button[data-testid="sidebar_panic_close"]) button:hover {{
  background-color:#a00000 !important;
  border-color:#a00000 !important;
}}
[data-testid="stButton"]>button[kind="primary"],.stButton>button[kind="primary"] {{
  background-color:{T["red"]} !important;color:white !important;border:none !important;font-weight:700 !important;
}}
[data-testid="stExpander"] {{
  background-color:{T["surface"]} !important;border:1px solid {T["border"]} !important;border-radius:6px !important;
}}
[data-testid="stDataFrame"],[data-testid="stDataFrame"] *,.stDataFrame {{
  background-color:{T["surface"]} !important;color:{T["text"]} !important;
}}
/* AG-grid / dataframe cell text */
.stDataFrame [role="gridcell"],
.stDataFrame [role="columnheader"],
.stDataFrame [role="row"],
.stDataFrame .dvn-scroller *,
[data-testid="stDataFrameResizable"] *,
[data-testid="stDataFrameResizable"] [role="gridcell"] {{
  color:{T["text"]} !important;
  background-color:{T["surface"]} !important;
}}
[data-testid="stAlert"] {{
  background-color:{T["surface"]} !important;border-color:{T["border"]} !important;color:{T["text"]} !important;
}}
hr {{ border-color:{T["border"]} !important; }}
.trade-card {{
  background:{T["surface"]} !important;border:1px solid {T["border"]};
  border-radius:8px;padding:1rem 1.2rem;margin-bottom:0.6rem;color:{T["text"]};
}}
.status-pill {{
  display:inline-block;padding:2px 10px;border-radius:20px;
  font-size:0.72rem;font-weight:600;letter-spacing:0.05em;text-transform:uppercase;
}}
.status-scanning {{ background:rgba(0,200,240,0.12);color:{T["accent"]}; }}
.status-in_trade {{ background:rgba(26,127,55,0.12);color:{T["green"]}; }}
.status-halted   {{ background:rgba(207,34,46,0.12);color:{T["red"]}; }}
.status-idle     {{ background:rgba(88,96,105,0.12);color:{T["muted"]}; }}
.status-standby  {{ background:rgba(180,120,0,0.12);color:#b27800; }}
.journal-table {{ overflow-x:auto; }}
code,pre {{ background:{T["surface"]} !important;color:{T["accent"]} !important; }}

/* ── METRIC CARDS ─────────────────────────────────────────────── */
.mc{{background:{T["surface"]};border:1px solid {T["border"]};border-radius:6px;padding:10px 12px;margin-top:0;margin-bottom:0}}
.ml{{font-size:.57rem;color:#374151;text-transform:uppercase;letter-spacing:.09em;margin-bottom:3px;font-weight:700}}
.mv{{font-size:1rem;font-weight:700;color:{T["text"]}}}
.md{{font-size:.57rem;color:{T["muted"]};margin-top:2px}}
.mrow{{display:grid;gap:6px;margin-bottom:0;padding:4px 2px;box-sizing:border-box;width:100%;overflow:hidden}}
.m8{{grid-template-columns:repeat(8,1fr)}}
.m6{{grid-template-columns:repeat(6,1fr)}}
.m5{{grid-template-columns:repeat(5,1fr)}}
.m4{{grid-template-columns:repeat(4,1fr)}}
.m3{{grid-template-columns:repeat(3,1fr)}}
/* Compact card values in 8-col grid so text doesn't overflow */
.mrow.m8 .mv{{font-size:.8rem!important}}
.mrow.m8 .ml{{font-size:.5rem!important}}
.mrow.m8 .md{{font-size:.48rem!important}}
.mrow.m8 .mc{{padding:7px 8px!important}}

/* ── COLOUR HELPERS ───────────────────────────────────────────── */
.c-grn{{color:{T["green"]}!important}}
.c-red{{color:{T["red"]}!important}}
.c-acc{{color:{T["accent"]}!important}}
.c-yel{{color:{T["yellow"]}!important}}
.c-pur{{color:{T["purple"]}!important}}
.c-mut{{color:{T["muted"]}!important}}

/* ── CELO TRADER BRANDING — luxury light mode ────────────────────── */
/* Deep navy metallic text on cool-white card with left accent stripe. */
.ct-brand {{
  font-family:'Playfair Display',Georgia,serif !important;
  font-weight:900;
  font-size:clamp(1.6rem,3.5vw,2.4rem);
  letter-spacing:0.18em;
  text-align:center;
  line-height:1.05;
  /* Navy → midnight → charcoal: luxury without going dark-mode */
  background:linear-gradient(
    180deg,
    #0a2540 0%,
    #0f2d52 25%,
    #1a3a5c 50%,
    #0f2d52 75%,
    #0a2540 100%
  );
  -webkit-background-clip:text;
  -webkit-text-fill-color:transparent;
  background-clip:text;
  filter:drop-shadow(0 1px 0 rgba(255,255,255,0.9));
  margin:0;
  padding:0;
  user-select:none;
}}
.ct-brand-wrap {{
  background:linear-gradient(135deg,#f8faff 0%,#ffffff 55%,#f4f7fd 100%);
  border:1px solid #dde4f0;
  border-left:3px solid #0a2540;
  border-radius:8px;
  padding:6px 20px 5px;
  margin-bottom:4px;
  text-align:center;
  box-shadow:0 2px 12px rgba(10,37,64,0.09),0 1px 3px rgba(0,0,0,0.04);
}}
.ct-sub {{
  font-family:'JetBrains Mono',monospace !important;
  font-size:0.55rem;
  letter-spacing:0.30em;
  color:#4a6080;
  text-transform:uppercase;
  margin-top:2px;
  margin-bottom:2px;
}}

/* ── CARD SHADOW SYSTEM — professional depth without hard outlines ─ */
/* Cards are separated by elevation (shadow), not black borders.     */
/* This mirrors Stripe/Linear/Vercel's design language.              */
[data-testid="stPlotlyChart"] > div {{
  border-radius:8px;
  overflow:hidden;
  box-shadow:0 1px 3px rgba(0,0,0,0.08),0 1px 2px rgba(0,0,0,0.05);
}}
[data-testid="stExpander"] {{
  border:1px solid {T["border"]} !important;
  border-radius:8px !important;
  box-shadow:0 1px 2px rgba(0,0,0,0.05) !important;
}}
.trade-card,.mc {{
  border:1px solid {T["border"]} !important;
  box-shadow:0 1px 2px rgba(0,0,0,0.04) !important;
}}

/* ── TOPBAR STRIP ─────────────────────────────────────────────── */
.live-topbar{{
  background:linear-gradient(135deg,#f8faff 0%,#ffffff 60%,#f4f7fd 100%);
  border:1px solid #dde4f0;border-radius:6px;
  display:flex;align-items:center;padding:5px 12px;gap:8px;margin-bottom:4px;
  flex-wrap:nowrap;overflow:hidden;
  box-shadow:0 1px 4px rgba(10,37,64,0.07);
}}
.tb-ticker{{font-family:'Syne',sans-serif;font-size:.95rem;font-weight:700;color:#0a2540}}
.tb-pnl-lbl{{font-size:.58rem;font-weight:700;color:#7a93ae;text-transform:uppercase;letter-spacing:.08em;line-height:1}}
.tb-pnl-val{{font-size:.9rem;font-weight:800;letter-spacing:-.01em;line-height:1.1}}
.tb-price{{font-size:.82rem;font-weight:600;color:{T["text"]}}}
.tb-chg{{font-size:.7rem;font-weight:600}}
.tb-sep{{width:1px;height:18px;background:#dde4f0;flex-shrink:0}}
.tb-right{{display:flex;align-items:center;gap:6px;font-size:.62rem;color:{T["muted"]}}}
.live-dot{{width:6px;height:6px;border-radius:50%;background:{T["green"]};
  display:inline-block;animation:ctpulse 2s infinite}}
@keyframes ctpulse{{0%,100%{{opacity:1}}50%{{opacity:.4}}}}

/* ── TIMEFRAME RADIO — compact pill style, no native dot ─────── */
/* The native Streamlit radio circle bleeds into adjacent rows.
   We hide it and restyle the container as a flat pill strip.     */
div[data-testid="stRadio"] {{
  padding:0!important;
  margin:0!important;
}}
div[data-testid="stRadio"] > div {{
  gap:0!important;
  flex-direction:row!important;
  align-items:center!important;
}}
div[data-testid="stRadio"] label {{
  padding:3px 10px!important;
  border:1px solid {T["border"]}!important;
  border-radius:4px!important;
  margin-right:4px!important;
  font-size:.72rem!important;
  font-weight:600!important;
  cursor:pointer!important;
  background:{T["surface"]}!important;
  color:{T["text"]}!important;
}}
div[data-testid="stRadio"] label:has(input:checked) {{
  background:#dbeafe!important;
  border-color:#0969da!important;
  color:#0969da!important;
}}
/* Hide the raw radio circle button */
div[data-testid="stRadio"] input[type="radio"] {{
  display:none!important;
}}

/* ── SIGNAL PILLS ─────────────────────────────────────────────── */
.pill{{padding:2px 8px;border-radius:20px;font-size:.6rem;font-weight:600;
  letter-spacing:.05em;text-transform:uppercase;display:inline-block}}
.pill-bull{{background:rgba(26,127,55,.12);color:{T["green"]};border:1px solid rgba(26,127,55,.25)}}
.pill-bear{{background:rgba(207,34,46,.12);color:{T["red"]};border:1px solid rgba(207,34,46,.25)}}
.pill-wait{{background:rgba(154,103,0,.10);color:{T["yellow"]};border:1px solid rgba(154,103,0,.25)}}

/* ── BADGES ───────────────────────────────────────────────────── */
.badge{{display:inline-block;padding:2px 7px;border-radius:999px;font-size:.58rem;font-weight:600}}
.b-bull{{background:rgba(26,127,55,.12);color:{T["green"]}}}
.b-bear{{background:rgba(207,34,46,.12);color:{T["red"]}}}
.b-man {{background:rgba(154,103,0,.10);color:{T["yellow"]}}}
.b-call{{background:rgba(26,127,55,.12);color:{T["green"]}}}
.b-put {{background:rgba(207,34,46,.12);color:{T["red"]}}}
.b-tp  {{background:rgba(26,127,55,.10);color:{T["green"]}}}
.b-sl  {{background:rgba(207,34,46,.10);color:{T["red"]}}}

/* ── CHECKBOX IN RIGHT PANEL — pad so it doesn't touch the edge ─ */
div[data-testid="column"]:last-child [data-testid="stCheckbox"] {{
  padding:4px 6px!important;
  border-radius:4px!important;
  background:{T["surface"]}!important;
  border:1px solid {T["border"]}!important;
  margin-top:2px!important;
}}
div[data-testid="column"]:last-child [data-testid="stCheckbox"] label p {{
  font-size:.72rem!important;
  font-weight:600!important;
}}

/* ── POSITION PANEL ───────────────────────────────────────────── */
/* col_pos is a narrow column — panel must fill without overflow.
   All child elements use box-sizing:border-box so padding never
   pushes content outside the column boundary.                      */
.pos-panel{{
  background:{T["surface"]};border:1px solid {T["border"]};
  border-radius:6px;font-family:'JetBrains Mono',monospace;
  box-sizing:border-box;width:100%;overflow:hidden;
  margin-top:0;
}}
.pos-head{{
  display:flex;align-items:center;justify-content:space-between;
  padding:8px 12px;border-bottom:1px solid {T["border"]};
  box-sizing:border-box;
}}
.pos-ht{{font-size:.62rem;color:{T["muted"]};text-transform:uppercase;letter-spacing:.08em}}
.pos-body{{
  padding:10px 12px 12px 12px;
  box-sizing:border-box;
  display:flex;flex-direction:column;gap:0;
}}
.pos-sym{{
  font-size:.80rem;font-weight:600;color:{T["accent"]};
  word-break:break-all;margin-bottom:1px;
}}
.pos-sub{{font-size:.58rem;color:{T["muted"]};margin-bottom:8px}}
.pos-divider{{height:1px;background:{T["border"]};margin:8px 0;flex-shrink:0}}
.prow{{
  display:flex;justify-content:space-between;align-items:baseline;
  margin-bottom:4px;font-size:.65rem;box-sizing:border-box;
}}
.pk{{color:{T["muted"]}}}
.pv{{font-weight:600;color:{T["text"]}}}
.pnl-box{{
  border-radius:4px;padding:7px 8px;text-align:center;
  margin:6px 0;box-sizing:border-box;
}}
.pnl-lbl{{font-size:.56rem;text-transform:uppercase;letter-spacing:.09em;margin-bottom:2px}}
.pnl-num{{font-size:1.1rem;font-weight:700;line-height:1.2}}
.prog-head{{
  display:flex;justify-content:space-between;
  font-size:.55rem;color:{T["muted"]};margin-bottom:3px;
}}
.prog-track{{
  height:5px;background:{T["border"]};border-radius:3px;
  overflow:hidden;margin-bottom:8px;
}}
.prog-fill{{height:100%;border-radius:3px}}

/* ── SIGNAL BASIS ROWS ────────────────────────────────────────── */
.sig-section{{
  font-size:.56rem;color:{T["muted"]};text-transform:uppercase;
  letter-spacing:.08em;margin:8px 0 5px;
}}
.sig-row{{
  display:flex;justify-content:space-between;align-items:center;
  padding:3px 0;border-bottom:1px solid {T["border"]};
  font-size:.63rem;box-sizing:border-box;gap:4px;
}}
.sig-row:last-child{{border-bottom:none}}
.sig-k{{color:{T["text"]};opacity:.8;font-size:.62rem;white-space:nowrap}}

/* ── HAMBURGER SIDEBAR TOGGLE (light mode only) ──────────────── */
/* White background, #333 border, minimum 32 × 32 px tap area.    */
[data-testid="stSidebarCollapsedControl"] {{
  position:fixed!important;
  top:8px!important;
  left:8px!important;
  z-index:999999!important;
  display:flex!important;
  align-items:center!important;
  justify-content:center!important;
  opacity:1!important;
  background:#ffffff!important;
  border:2px solid #333333!important;
  border-radius:8px!important;
  min-width:36px!important;
  min-height:36px!important;
  padding:0!important;
  box-shadow:0 2px 8px rgba(0,0,0,.15)!important;
  transition:box-shadow .15s ease,transform .1s ease!important;
}}
[data-testid="stSidebarCollapsedControl"]:hover {{
  box-shadow:0 4px 14px rgba(0,0,0,.25)!important;
  transform:scale(1.06)!important;
}}
[data-testid="stSidebarCollapsedControl"] button svg {{
  display:none!important;
}}
[data-testid="stSidebarCollapsedControl"] button::before {{
  content:"☰"!important;
  font-size:20px!important;
  font-weight:900!important;
  color:#222222!important;
  line-height:1!important;
  padding:8px 10px!important;
  display:block!important;
  letter-spacing:1px!important;
}}
[data-testid="stSidebarCollapsedControl"] button {{
  background:transparent!important;
  border:none!important;
  cursor:pointer!important;
  padding:0!important;
  min-width:36px!important;
  min-height:36px!important;
  display:flex!important;
  align-items:center!important;
  justify-content:center!important;
}}
/* Inside sidebar: simple close chevron — keep it understated */
[data-testid="stSidebarCollapseButton"] button {{
  background:transparent!important;
  border:none!important;
}}
[data-testid="stSidebarCollapseButton"] button svg {{
  fill:{T["muted"]}!important;
}}
/* Inside open sidebar: keep the native close button but style it */
[data-testid="stSidebarCollapseButton"] button {{
  background:transparent!important;
  border:none!important;
}}
[data-testid="stSidebarCollapseButton"] button svg {{
  fill:{T["muted"]}!important;
}}
/* Make the black Streamlit header bar invisible without hiding its children.
   The sidebar toggle lives inside it — hiding the element kills the button. */
header[data-testid="stHeader"] {{
  background:transparent!important;
  border-bottom:none!important;
  box-shadow:none!important;
}}
/* Hide the deploy/settings toolbar icons specifically */
[data-testid="stToolbarActions"],
[data-testid="stDecoration"] {{
  display:none!important;
}}
/* Reduce top padding now that the header is gone;
   keep just enough room for the hamburger button */
[data-testid="stMain"] > div:first-child {{
  padding-top:8px!important;
}}

/* ── PLOTLY CHART WRAPPER — kill all Streamlit padding ──────── */
[data-testid="stPlotlyChart"] {{
  margin-top:-25px!important;
  margin-right:0!important;
  margin-bottom:0!important;
  margin-left:0!important;
  padding:0!important;
  line-height:0!important;
  display:block!important;
}}
/* Collapse the vertical block gap between adjacent chart elements */
[data-testid="stVerticalBlockBorderWrapper"],
[data-testid="stVerticalBlock"] {{
  gap:0!important;
  row-gap:0!important;
  margin-top:0!important;
}}
/* Kill default Streamlit margins across all block containers */
[data-testid="stMarkdownContainer"],
[data-testid="stElementContainer"],
[data-testid="stWidgetLabel"] {{
  margin-top:0!important;
  margin-bottom:0!important;
}}
/* Plotly chart element — remove bottom gap so signal pill sits flush */
[data-testid="stPlotlyChart"] {{
  margin-bottom:0!important;
  padding-bottom:0!important;
}}
/* Primary metric delta — 14pt for legibility */
[data-testid="stMetricDelta"] {{
  font-size:14pt!important;
}}

/* ── CHART CONTAINER ─────────────────────────────────────────── */
.chart-wrap{{background:{T["surface"]};border:1px solid {T["border"]};
  border-radius:6px;padding:0;margin-bottom:0}}
.chart-wrap [data-testid="stPlotlyChart"]{{margin:0!important;padding:0!important}}
.chart-hd{{display:flex;align-items:center;justify-content:space-between;
  padding:7px 12px;border-bottom:1px solid {T["border"]}}}
.chart-ht{{font-size:.62rem;color:{T["muted"]};text-transform:uppercase;letter-spacing:.08em}}
.legend{{display:flex;gap:10px}}
.leg{{display:flex;align-items:center;gap:4px;font-size:.57rem;color:{T["muted"]}}}
.leg-line{{width:12px;height:2px;border-radius:1px;display:inline-block}}

/* ── PRICE TICKER BAR ─────────────────────────────────────────── */
@keyframes ticker-scroll {{
  0%   {{ transform: translateX(0); }}
  100% {{ transform: translateX(-50%); }}
}}
.ticker-wrap {{
  position:fixed;bottom:0;left:0;right:0;z-index:9999;
  background:#ffffff;border-top:1px solid #e5e7eb;
  box-shadow:0 -2px 8px rgba(0,0,0,0.06);
  height:32px;overflow:hidden;display:flex;align-items:center;
}}
.ticker-track {{
  display:flex;align-items:center;white-space:nowrap;
  animation:ticker-scroll 40s linear infinite;
  gap:0;
}}
.ticker-item {{
  display:inline-flex;align-items:center;gap:6px;
  padding:0 24px;font-size:12px;font-family:'JetBrains Mono',monospace;
  border-right:1px solid #cccccc;
}}
/* Scoped under .ticker-wrap so specificity = 0-2-0 (20 pts).
   Beats [data-testid="stMarkdownContainer"] span at 0-1-1 (11 pts)
   even when both carry !important.                                    */
.ticker-wrap .ticker-sym {{ color:#111827!important;font-weight:700; }}
.ticker-wrap .ticker-px  {{ color:#374151!important; }}
.ticker-wrap .ticker-up  {{ color:#16a34a!important;font-weight:700; }}
.ticker-wrap .ticker-dn  {{ color:#dc2626!important;font-weight:700; }}
</style>
""", unsafe_allow_html=True)

# ── Bot state file helpers ─────────────────────────────────────────────────────
# trading_logic.py writes bot_state.json on every tick.
# The dashboard reads it so the Live Trading page always reflects the live bot.
_BOT_STATE_PATH = Path(__file__).resolve().parent / "bot_state.json"

def _read_bot_state() -> dict:
    defaults = {
        "running": False,
        "account_balance": float(get_settings().get("last_known_balance", STARTING_CAPITAL)),
        "session_pnl": 0.0,
        "status": "offline",
        "current_ticker": None,
        "last_signal": None,
        "market_open": False,
        "last_update": "--",
        "network_ok": True,   # assume ok when no state file exists
        # Risk-sizing visibility — surfaced proactively on Live Trading page
        "risk_budget_usd": 0.0,
        "max_affordable_premium": 0.0,
        "last_eval_ticker": None,
        "last_eval_opt_type": None,
        "last_eval_premium": None,
        "last_eval_eff_entry": None,
        "last_eval_time": None,
    }
    if _BOT_STATE_PATH.exists():
        try:
            with open(_BOT_STATE_PATH) as f:
                saved = json.load(f)
            defaults.update(saved)
        except (json.JSONDecodeError, OSError):
            pass
    return defaults


def _bot_engine_alive(last_update: str, max_age_minutes: int = 2) -> bool:
    """
    True if bot_state.json's "last_update" timestamp was written within the
    last `max_age_minutes` -- i.e. a real trading_logic.py engine is actively
    ticking RIGHT NOW, whether that's the in-dashboard thread started by the
    sidebar's "Start" button, or a standalone `main.py --paper` process
    launched via CeloTrader.command (which the sidebar buttons can't see).

    "last_update" is written in two different formats depending on which code
    path last fired: a tz-aware ISO datetime (during active scanning) or a
    bare "HH:MM:SS" string assumed to be today in ET (during market-closed
    standby ticks). Both are normalized to US/Eastern before comparing.
    """
    if not last_update or last_update == "--":
        return False
    try:
        ts = pd.to_datetime(last_update)
        now_et = pd.Timestamp.now(tz="America/New_York")
        ts = ts.tz_localize("America/New_York") if ts.tzinfo is None else ts.tz_convert("America/New_York")
        return (now_et - ts) < pd.Timedelta(minutes=max_age_minutes)
    except Exception:
        return False


def generate_simulation_data() -> pd.DataFrame:
    """
    Reproducible synthetic OHLCV bars anchored to today's ET trading session.

    Three phases are explicitly sculpted so all three strategies fire:

      Phase 1 — ORB breakout (bars 0-8):
        Bar 0 (09:30) = Opening Range.
        Bar 3 (09:45) = Bullish ORB breakout above OR High, 3.2× volume spike.
        Bars 4-8      = Continuation rally to session high.

      Phase 2 — Mid-day breakdown (bars 9-24):
        Bars 9-15  = Steady decline from session peak.
        Bar 16 (10:50) = Dead-cat bounce = Lower High (LH) — confirms downtrend.
        Bars 17-23 = Accelerate through OR Low.
        Bar 24 (11:30) = MID_BRK trigger: close below OR Low, 2.5× volume spike.
        Gate checks: close < or_low ✓, close < vwap ✓, confirmed_lower_high ✓.

      Phase 3 — Afternoon reversal (bars 25-52):
        Bars 25-35 = Recovery from the breakdown low.
        Bar 36 (13:00) = Higher Low (HL) dip — last_SL > prev_SL ✓.
        Bars 37-51 = Build toward the mid-day LH (bar 16's high = local resistance).
        Bar 52 (13:50) = AFT_REV trigger: close breaks above last swing high (LH),
                         2.2× volume spike. Gate: confirmed_higher_low ✓, BOS ✓.

    Timestamps are tz-naive ET so they pass all downstream hour/minute checks.
    """
    import numpy as np
    np.random.seed(42)
    bars = 78   # 09:30 → 15:55 ET (full session)

    # ── Anchor to today's ET session (09:30, tz-naive) ───────────────────────
    _today_str = date.today().isoformat()
    times = pd.date_range(
        start=f"{_today_str} 09:30:00",
        periods=bars,
        freq="5min",
    )

    # ── Base arrays — will be partially overwritten by structured phases ──────
    close  = 500.0 + np.cumsum(np.random.normal(0.05, 0.80, size=bars))
    high   = close + np.abs(np.random.normal(0.50, 0.20, size=bars))
    low    = close - np.abs(np.random.normal(0.50, 0.20, size=bars))
    open_p = np.roll(close, 1)
    open_p[0] = close[0] + 0.10
    volume = np.random.randint(10_000, 45_000, size=bars).astype(float)

    # Reference levels from bar 0 (Opening Range candle)
    _or_high_val = float(high[0])
    _or_low_val  = float(low[0])
    _base_px     = float(close[0])   # ~500

    # ── PHASE 1: ORB breakout ─────────────────────────────────────────────────
    # Bars 1-2: tight OR consolidation
    close[1] = _base_px - 0.15;  high[1] = close[1] + 0.25; low[1] = close[1] - 0.25; open_p[1] = close[0]
    close[2] = _base_px + 0.05;  high[2] = close[2] + 0.22; low[2] = close[2] - 0.22; open_p[2] = close[1]

    # Bar 3 (09:45): bullish ORB breakout — close clears OR High, volume 3.2×
    close[3]  = _or_high_val + 1.50
    high[3]   = close[3]  + 0.50
    low[3]    = close[3]  - 0.35
    open_p[3] = _or_high_val + 0.10
    _avg_at_3 = float(np.mean(volume[:3]))
    volume[3] = _avg_at_3 * 3.2

    # Bars 4-8: post-ORB continuation to session high
    _orb_cls = float(close[3])
    _peak    = _orb_cls + 1.80   # session peak ≈ bar 8
    for _j in range(4, 9):
        _f = (_j - 3) / 5.0
        close[_j]  = _orb_cls + _f * (_peak - _orb_cls)
        high[_j]   = close[_j] + 0.35
        low[_j]    = close[_j] - 0.28
        open_p[_j] = close[_j - 1]

    # ── PHASE 2: Mid-day decline → breakdown at bar 24 (11:30 ET) ────────────
    # Bars 9-15: steady sell-off from the session high
    _peak_cls = float(close[8])
    _interim  = _or_low_val - 0.60   # approaching OR Low by bar 15
    for _j in range(9, 16):
        _f = (_j - 8) / 7.0
        close[_j]  = _peak_cls + _f * (_interim - _peak_cls)
        high[_j]   = close[_j] + 0.38
        low[_j]    = close[_j] - 0.38
        open_p[_j] = close[_j - 1]

    # Bar 16 (10:50 ET): dead-cat bounce = Lower High (LH); confirms downtrend.
    # high[16] must satisfy: high[16] < high[8]  (LH < prev SH → confirmed_lower_high ✓)
    close[16]  = float(close[15]) + 0.65
    high[16]   = close[16] + 0.28   # the LH that AFT_REV will eventually break above
    low[16]    = float(close[15]) - 0.12
    open_p[16] = close[15]

    # Bars 17-23: acceleration into breakdown (below OR Low)
    _lh_cls   = float(close[16])
    _brk_tgt  = _or_low_val - 1.60   # final breakdown target
    for _j in range(17, 24):
        _f = (_j - 16) / 7.0
        close[_j]  = _lh_cls + _f * (_brk_tgt - _lh_cls)
        high[_j]   = close[_j] + 0.32
        low[_j]    = close[_j] - 0.42
        open_p[_j] = close[_j - 1]

    # Bar 24 (11:30 ET): MID_BRK trigger — explicit breakdown candle
    close[24]  = _or_low_val - 1.60
    high[24]   = close[24] + 0.18
    low[24]    = close[24] - 0.52    # SL1 — the low that bar 36's HL must exceed
    open_p[24] = close[23]
    _avg_at_24 = float(np.mean(volume[14:24]))
    volume[24] = _avg_at_24 * 2.5    # volume surge on breakdown

    # ── PHASE 3: Recovery → Higher Low → AFT_REV at bar 52 (13:50 ET) ────────
    # Bars 25-35: gradual recovery off the breakdown low
    _bot_cls  = float(close[24])
    _rec_tgt  = _bot_cls + 1.00
    for _j in range(25, 36):
        _f = (_j - 24) / 11.0
        close[_j]  = _bot_cls + _f * (_rec_tgt - _bot_cls)
        high[_j]   = close[_j] + 0.33
        low[_j]    = close[_j] - 0.33
        open_p[_j] = close[_j - 1]

    # Bar 36 (13:00 ET): Higher Low (HL) dip — low[36] must be > low[24] ✓
    close[36]  = float(close[35]) - 0.38
    high[36]   = close[36] + 0.22
    low[36]    = close[36] - 0.22   # HL: > low[24] because close[36] >> close[24]
    open_p[36] = close[35]

    # Bars 37-51: build toward the LH resistance (high[16]) for the BOS
    _hl_cls   = float(close[36])
    _bos_tgt  = float(high[16]) + 1.30   # AFT_REV trigger level
    for _j in range(37, 52):
        _f = (_j - 36) / 15.0
        close[_j]  = _hl_cls + _f * (_bos_tgt - _hl_cls)
        high[_j]   = close[_j] + 0.28
        low[_j]    = close[_j] - 0.28
        open_p[_j] = close[_j - 1]

    # Bar 52 (13:50 ET): AFT_REV trigger — close breaks above last SH (LH at bar 16)
    close[52]  = float(high[16]) + 1.30
    high[52]   = close[52] + 0.32
    low[52]    = close[52] - 0.25
    open_p[52] = close[51]
    _avg_at_52 = float(np.mean(volume[40:52]))
    volume[52] = _avg_at_52 * 2.2    # volume confirmation for the reversal

    # ── PHASE 4: Post-reversal drift to close (bars 53-77) ───────────────────
    for _j in range(53, bars):
        _drift     = np.random.normal(0.08, 0.65)
        close[_j]  = close[_j - 1] + _drift
        high[_j]   = close[_j] + np.abs(np.random.normal(0.42, 0.18))
        low[_j]    = close[_j] - np.abs(np.random.normal(0.42, 0.18))
        open_p[_j] = close[_j - 1]

    # Secondary volume spikes on non-forced bars (visual richness)
    for _si in (10, 32, 55):
        if _si not in (3, 24, 52) and _si < bars:
            volume[_si] = float(np.mean(volume[max(0, _si - 10): _si])) * 2.0

    return pd.DataFrame({
        "time":   times,
        "open":   open_p,
        "high":   high,
        "low":    low,
        "close":  close,
        "volume": volume.astype(int),
    })


# ── Sim data loader — real Alpaca bars with synthetic fallback ────────────────
def _load_sim_bars(ticker: str, timeframe: str = "5Min") -> tuple[pd.DataFrame, str]:
    """
    Fetch real historical OHLCV bars for simulation / paper-replay mode.

    Priority:
      1. AlpacaClient.get_session_bars() — today's or the most-recent session
      2. AlpacaClient.get_bars(limit=…)  — broader trailing fetch, sliced to one day
      3. generate_simulation_data()      — synthetic fallback (no API / offline)

    Returns (DataFrame, source_label):
      "live"      — market open, bars through the current minute
      "session"   — most recent completed session (market closed)
      "historical"— trailing fetch sliced to one trading session
      "synthetic" — no Alpaca connection, using generated bars (with a warning)

    All returned DataFrames have tz-naive ET timestamps and the columns:
    time, open, high, low, close, volume  (standard bars_to_df output).
    """
    import logging as _log
    _lg = _log.getLogger("celo_trader.dashboard.sim")
    try:
        from broker import AlpacaClient as _SimAC
        _ac = _SimAC()

        # ── Primary: session-scoped fetch ─────────────────────────────────────
        _bars, _err, _is_live = _ac.get_session_bars(ticker, timeframe)
        if not _err and _bars:
            _df = _b2d(_bars)                         # UTC → ET tz-naive
            _src = "live" if _is_live else "session"
            # If fewer than 10% of bars are outside 09:29–16:01, those are
            # orphaned pre/post-market stubs from a mixed fallback fetch.
            # Drop them so the chart never shows a confusing gap at session open.
            if not _df.empty:
                _reg_mask = (_df["time"].dt.hour > 9) | (
                    (_df["time"].dt.hour == 9) & (_df["time"].dt.minute >= 29)
                )
                _out_count = (~_reg_mask).sum()
                if _out_count > 0 and _out_count < max(3, len(_df) * 0.10):
                    _df = _df[_reg_mask].reset_index(drop=True)
                    _lg.info(
                        "Stripped %d orphaned pre/post-market stub bars from %s feed",
                        _out_count, ticker,
                    )
            _lg.info("Sim bars (%s): %d %s bars for %s", _src, len(_df), timeframe, ticker)
            return _df, _src

        # ── Fallback: trailing fetch, slice to the most recent trading day ────
        _limit = 500 if timeframe == "1Min" else 120
        _bars2, _err2 = _ac.get_bars(ticker, timeframe, limit=_limit)
        if not _err2 and _bars2:
            _df2 = _b2d(_bars2)
            if not _df2.empty:
                # Keep only the last calendar date to avoid multi-day overlap
                _last_date = _df2["time"].dt.date.max()
                _df2 = _df2[_df2["time"].dt.date == _last_date].reset_index(drop=True)
            if not _df2.empty:
                _lg.info(
                    "Sim bars (historical fallback): %d %s bars for %s on %s",
                    len(_df2), timeframe, ticker, _last_date,
                )
                return _df2, "historical"

    except Exception as _e:
        _lg.warning("Sim bar fetch failed (%s %s): %s — trying yfinance", ticker, timeframe, _e)

    # ── yfinance fallback — covers ETFs (SPY/QQQ) that IEX feed doesn't carry ──
    # IEX exchange only lists equities; ETFs trade on NYSE Arca and return 0
    # bars from Alpaca's free IEX feed.  yfinance is always free and has full
    # coverage for all US symbols including index ETFs.
    try:
        import yfinance as _yf
        _yf_interval = "5m" if timeframe in ("5Min", "5m") else "1m"
        # "2d" gives today + yesterday so market-closed views still have data
        # prepost=True fetches pre-market (04:00–09:30) and post-market bars.
        _yf_df = _yf.download(ticker, period="2d", interval=_yf_interval,
                               progress=False, auto_adjust=True, prepost=True)
        if not _yf_df.empty:
            # Flatten MultiIndex columns if present (yfinance ≥0.2 wraps in ticker level)
            if isinstance(_yf_df.columns, pd.MultiIndex):
                _yf_df.columns = _yf_df.columns.get_level_values(0)
            _yf_df = _yf_df.rename(columns={
                "Open": "open", "High": "high", "Low": "low",
                "Close": "close", "Volume": "volume",
            })
            _yf_df.index.name = "time"
            _yf_df = _yf_df.reset_index()
            # Convert to ET tz-naive (yfinance returns UTC or America/New_York)
            if hasattr(_yf_df["time"].dtype, "tz") and _yf_df["time"].dt.tz is not None:
                _yf_df["time"] = (_yf_df["time"]
                                  .dt.tz_convert("America/New_York")
                                  .dt.tz_localize(None))
            # Keep pre-market + regular session + post-market (04:00–20:00 ET).
            # Do NOT filter to 09:30–16:00 — that was stripping pre-market candles.
            _yf_df = _yf_df[
                (_yf_df["time"].dt.hour >= 4) & (_yf_df["time"].dt.hour < 20)
            ]
            if not _yf_df.empty:
                _last_yf_date = _yf_df["time"].dt.date.max()
                _yf_df = _yf_df[_yf_df["time"].dt.date == _last_yf_date].reset_index(drop=True)
            _yf_df = _yf_df[["time", "open", "high", "low", "close", "volume"]]
            if not _yf_df.empty:
                _lg.info("yfinance fallback: %d %s bars for %s", len(_yf_df), timeframe, ticker)
                return _yf_df, "historical"
    except Exception as _yfe:
        _lg.warning("yfinance fallback failed for %s: %s — using synthetic data", ticker, _yfe)

    # ── Synthetic fallback (offline / bad API key / yfinance blocked) ────────────
    _lg.warning("Sim mode: no bar data available — synthetic fallback for %s", ticker)
    _synth5 = generate_simulation_data()
    if timeframe == "1Min":
        # Upsample 5-min → 1-min via forward-fill so the 1m chart has data
        try:
            _synth1 = (
                _synth5.set_index("time")
                .resample("1min")
                .ffill()
                .reset_index()
            )
            _synth1["volume"] = (_synth1["volume"] / 5).clip(lower=1).astype(int)
            return _synth1, "synthetic"
        except Exception:
            pass
    return _synth5, "synthetic"


# ── Shared HTML table helper ──────────────────────────────────────────────────
# Renders a pandas DataFrame (or list-of-dicts) as a plain HTML table so it
# shows up correctly in Streamlit's light theme without shadow-DOM CSS fights.
def _html_table(data, col_widths=None) -> str:
    """
    Convert a DataFrame or list-of-dicts to an inline-styled HTML table.

    Parameters
    ----------
    data        : pd.DataFrame or list[dict]
    col_widths  : optional list of CSS width strings, e.g. ["30%", "15%", ...]

    Returns
    -------
    HTML string for use with st.markdown(..., unsafe_allow_html=True)
    """
    import pandas as _pd
    if not isinstance(data, _pd.DataFrame):
        data = _pd.DataFrame(data)
    if data.empty:
        return "<p style='color:#57606a;font-size:0.85rem;'>No data.</p>"

    cols = list(data.columns)
    w = col_widths or []

    header_cells = "".join(
        f"<th style='text-align:left;padding:5px 8px;"
        f"border-bottom:2px solid #d0d7de;color:#1f2328;"
        f"{'width:'+w[i]+';' if i < len(w) else ''}'>{c}</th>"
        for i, c in enumerate(cols)
    )
    rows_html = ""
    for ri, row in data.iterrows():
        bg = "#f6f8fa" if ri % 2 == 0 else "#ffffff"
        cells = "".join(
            f"<td style='padding:5px 8px;color:#1f2328;"
            f"border-bottom:1px solid #eaecef;"
            f"word-wrap:break-word;overflow-wrap:break-word;'>{row[c]}</td>"
            for c in cols
        )
        rows_html += f"<tr style='background:{bg};'>{cells}</tr>"

    return (
        "<div style='overflow-x:auto;'>"
        "<table style='width:100%;border-collapse:collapse;font-size:0.84rem;'>"
        f"<thead><tr>{header_cells}</tr></thead>"
        f"<tbody>{rows_html}</tbody>"
        "</table></div>"
    )


# ── Live balance fetch — runs every render so dashboard never shows $0 ─────────
# LIVE_STATE lives in trading_logic but the dashboard is a separate process.
# We fetch directly from Alpaca here so the balance is always current.
try:
    from broker import AlpacaClient as _AC
    _ac = _AC()
    _acct = _ac.get_account()
    if _acct and float(_acct.get("equity", 0)) > 0:
        LIVE_STATE["account_balance"] = float(_acct["equity"])
        LIVE_STATE["status"] = "running"
    elif LIVE_STATE.get("account_balance", 0) == 0:
        _lkb = get_settings().get("last_known_balance", 0)
        if _lkb:
            LIVE_STATE["account_balance"] = float(_lkb)
except Exception:
    _lkb = get_settings().get("last_known_balance", 0)
    if _lkb and LIVE_STATE.get("account_balance", 0) == 0:
        LIVE_STATE["account_balance"] = float(_lkb)

# ── Nav session state — initialise before sidebar renders ─────────────────────
if "nav_page" not in st.session_state:
    st.session_state["nav_page"] = "brief"

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
        ("📋  Daily Brief",     "brief"),
        ("🖥  Live Trading",    "live"),
        ("📊  Performance",     "perf"),
        ("📓  Trade Journal",   "journal"),
        ("🔬  Session Audit",   "audit"),
        (None, None),           # section separator
        ("🗺  Income Roadmap",  "roadmap"),
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
page = st.session_state.get("nav_page", "brief")
# Convenience alias used throughout page bodies
balance = LIVE_STATE.get("account_balance", STARTING_CAPITAL)

# ═══════════════════════════════════════════════════════════════════════════════
# DAILY TRADE PLAN — generated once at 09:15 ET, displayed as banner on Live page
# ═══════════════════════════════════════════════════════════════════════════════

def _generate_trade_plan(ticker: str) -> dict | None:
    """
    Pull yesterday's OHLC, the rolling 5-day weekly range, and today's
    pre-market bars (04:00–09:15 ET).  Returns a plain-English trade-plan
    dict or None if data is unavailable.

    Keys returned:
      ticker, yest_open, yest_high, yest_low, yest_close,
      week_high, week_low, pm_high, pm_low, pm_last,
      gap_type, gap_pct, inside_range, bias, bias_reason,
      key_levels, generated_at
    """
    import datetime as _dt2
    try:
        import pytz as _pytz2
        _ET = _pytz2.timezone("America/New_York")
        _now_et = _dt2.datetime.now(_ET)
    except ImportError:
        _tz_off = _dt2.timezone(_dt2.timedelta(hours=-4))
        _now_et = _dt2.datetime.utcnow().replace(tzinfo=_tz_off)

    try:
        from broker import AlpacaClient as _PlanAC
        _bkr = _PlanAC()
        if _bkr is None:
            return None

        # ── Yesterday's daily OHLC ────────────────────────────────────────────
        _daily_bars, _err = _bkr.get_bars(ticker, "1Day", limit=10)
        if _err or not _daily_bars:
            return None

        # Alpaca returns bars newest-last; sort by time just in case
        _daily_bars = sorted(_daily_bars, key=lambda b: b.get("t", ""))
        # Most recent COMPLETED session = last bar whose date < today
        _today_str = _now_et.date().isoformat()
        _prev_bars = [b for b in _daily_bars if str(b.get("t", ""))[:10] < _today_str]
        if not _prev_bars:
            return None
        _yest = _prev_bars[-1]
        yest_open  = float(_yest.get("o", 0) or 0)
        yest_high  = float(_yest.get("h", 0) or 0)
        yest_low   = float(_yest.get("l", 0) or 0)
        yest_close = float(_yest.get("c", 0) or 0)
        if yest_close <= 0:
            return None

        # ── Weekly high/low (last 5 trading sessions) ─────────────────────────
        _week_bars = _prev_bars[-5:]
        week_high = max(float(b.get("h", 0) or 0) for b in _week_bars)
        week_low  = min(float(b.get("l", 0) or 0) for b in _week_bars if float(b.get("l", 0) or 0) > 0)
        week_range = week_high - week_low

        # ── Pre-market bars (04:00–09:15 ET today) ───────────────────────────
        # Alpaca extended-hours bars endpoint
        try:
            _pm_start = _now_et.replace(hour=4, minute=0, second=0, microsecond=0)
            _pm_end   = _now_et.replace(hour=9, minute=15, second=0, microsecond=0)
            _pm_url   = f"{_bkr.data}/v2/stocks/{ticker}/bars"
            _pm_params = {
                "timeframe":  "5Min",
                "start":      _pm_start.isoformat(),
                "end":        _pm_end.isoformat(),
                "limit":      100,
                "adjustment": "split",
                "feed":       "sip",
            }
            _pm_resp = _bkr.session.get(_pm_url, params=_pm_params, timeout=8)
            _pm_data = _pm_resp.json() if _pm_resp.status_code == 200 else {}
            _pm_bars = _pm_data.get("bars", [])
        except Exception:
            _pm_bars = []

        pm_high = max((float(b.get("h", 0) or 0) for b in _pm_bars), default=0.0)
        pm_low  = min((float(b.get("l", 0) or 0) for b in _pm_bars if float(b.get("l", 0) or 0) > 0), default=0.0)
        pm_last = float(_pm_bars[-1].get("c", 0) or 0) if _pm_bars else 0.0

        # If no pre-market data (weekend / data not available), use yesterday close
        if pm_last <= 0:
            pm_last = yest_close
        if pm_high <= 0:
            pm_high = yest_close
        if pm_low  <= 0:
            pm_low  = yest_close

        # ── Gap analysis ──────────────────────────────────────────────────────
        gap_pct   = (pm_last - yest_close) / yest_close * 100
        if gap_pct > 0.30:
            gap_type = "Gap Up"
        elif gap_pct < -0.30:
            gap_type = "Gap Down"
        else:
            gap_type = "Flat Open"

        # Inside or outside yesterday's range?
        inside_range = (pm_last <= yest_high) and (pm_last >= yest_low)

        # ── Overnight high / low context ──────────────────────────────────────
        overnight_high = pm_high
        overnight_low  = pm_low

        # ── Primary bias logic ────────────────────────────────────────────────
        # Score: +1 for each bullish factor, -1 for each bearish factor
        _score = 0
        _reasons: list[str] = []

        # Factor 1 — Gap direction
        if gap_pct > 0.50:
            _score += 2
            _reasons.append(f"Price is gapping UP {gap_pct:+.2f}% above yesterday's close (strong buyer interest overnight)")
        elif gap_pct > 0.15:
            _score += 1
            _reasons.append(f"Small gap up {gap_pct:+.2f}% — slight edge to buyers at open")
        elif gap_pct < -0.50:
            _score -= 2
            _reasons.append(f"Price is gapping DOWN {gap_pct:+.2f}% below yesterday's close (sellers in control overnight)")
        elif gap_pct < -0.15:
            _score -= 1
            _reasons.append(f"Small gap down {gap_pct:+.2f}% — slight edge to sellers at open")
        else:
            _reasons.append(f"Opening near yesterday's close (flat gap of {gap_pct:+.2f}%) — no strong overnight move")

        # Factor 2 — Pre-market last price vs yesterday's midpoint
        yest_mid = (yest_high + yest_low) / 2
        if pm_last > yest_mid:
            _score += 1
            _reasons.append(f"Pre-market price (${pm_last:.2f}) is above yesterday's midpoint (${yest_mid:.2f}) — buyers holding the high half")
        elif pm_last < yest_mid:
            _score -= 1
            _reasons.append(f"Pre-market price (${pm_last:.2f}) is below yesterday's midpoint (${yest_mid:.2f}) — sellers pressing the low half")

        # Factor 3 — Opening inside vs outside yesterday's range
        if not inside_range and pm_last > yest_high:
            _score += 1
            _reasons.append(f"Price is already ABOVE yesterday's high (${yest_high:.2f}) — breakout territory, CALL bias")
        elif not inside_range and pm_last < yest_low:
            _score -= 1
            _reasons.append(f"Price is already BELOW yesterday's low (${yest_low:.2f}) — breakdown territory, PUT bias")
        else:
            _reasons.append(f"Price is INSIDE yesterday's range (${yest_low:.2f} – ${yest_high:.2f}) — ORB will decide direction")

        # Factor 4 — Weekly range position
        if week_range > 0:
            _wk_pos = (pm_last - week_low) / week_range  # 0=week low, 1=week high
            if _wk_pos > 0.75:
                _score += 1
                _reasons.append(f"Near the TOP of the week's range ({_wk_pos*100:.0f}% of week) — momentum is up for the week")
            elif _wk_pos < 0.25:
                _score -= 1
                _reasons.append(f"Near the BOTTOM of the week's range ({_wk_pos*100:.0f}% of week) — momentum is down for the week")
            else:
                _reasons.append(f"In the middle of the week's range ({_wk_pos*100:.0f}% of week) — no weekly bias edge")

        # ── Bias decision ─────────────────────────────────────────────────────
        if _score >= 2:
            bias = "BULLISH"
            bias_emoji = "🟢"
            bias_short = "Watching for CALL (buy) at 09:30 ORB breakout above OR High"
        elif _score <= -2:
            bias = "BEARISH"
            bias_emoji = "🔴"
            bias_short = "Watching for PUT (sell) at 09:30 ORB breakdown below OR Low"
        else:
            bias = "NEUTRAL"
            bias_emoji = "⚪"
            bias_short = "Mixed signals — let the 09:30 ORB candle decide the direction, do not pre-bias"

        # ── Key levels ────────────────────────────────────────────────────────
        key_levels = {
            "Yesterday High":    f"${yest_high:.2f}  ← price above this = clear CALL territory",
            "Yesterday Low":     f"${yest_low:.2f}  ← price below this = clear PUT territory",
            "Yesterday Close":   f"${yest_close:.2f}  ← overnight reference price",
            "Pre-Market High":   f"${pm_high:.2f}  ← overnight buyers topped out here",
            "Pre-Market Low":    f"${pm_low:.2f}  ← overnight sellers bottomed here",
            "Week High":         f"${week_high:.2f}  ← 5-day ceiling",
            "Week Low":          f"${week_low:.2f}  ← 5-day floor",
        }

        return {
            "ticker":        ticker,
            "yest_open":     yest_open,
            "yest_high":     yest_high,
            "yest_low":      yest_low,
            "yest_close":    yest_close,
            "week_high":     week_high,
            "week_low":      week_low,
            "pm_high":       pm_high,
            "pm_low":        pm_low,
            "pm_last":       pm_last,
            "gap_type":      gap_type,
            "gap_pct":       gap_pct,
            "inside_range":  inside_range,
            "bias":          bias,
            "bias_emoji":    bias_emoji,
            "bias_short":    bias_short,
            "reasons":       _reasons,
            "key_levels":    key_levels,
            "score":         _score,
            "generated_at":  _now_et.strftime("%I:%M %p ET"),
        }

    except Exception as _e:
        import logging as _tp_log
        _tp_log.getLogger("celo_trader.dashboard").warning(
            "Daily trade plan generation failed: %s", _e
        )
        return None


def _render_trade_plan_banner(plan: dict) -> None:
    """
    Render the Daily Trade Plan as a Bloomberg/CNN-style financial brief.
    Premium newsletter aesthetic: dark masthead, structured data panels,
    clean sans-serif typography, muted color palette with signal accents.
    """
    if plan is None:
        return

    bias     = plan["bias"]
    ticker   = plan["ticker"]
    gap_pct  = plan["gap_pct"]
    score    = plan["score"]

    # ── Color tokens by bias ──────────────────────────────────────────────────
    if bias == "BULLISH":
        _accent   = "#16a34a"   # green
        _accent_l = "#dcfce7"
        _accent_t = "#14532d"
        _badge_bg = "#16a34a"
        _badge_tx = "#ffffff"
        _signal   = "CALL"
        _action   = f"Watch for breakout ABOVE ${plan['yest_high']:.2f} on elevated volume."
        _action_d = (
            f"If the first 5-min candle closes above OR High with ≥2× volume, "
            f"bot enters a CALL. Weak open (small body, thin volume) = stand aside."
        )
    elif bias == "BEARISH":
        _accent   = "#dc2626"
        _accent_l = "#fee2e2"
        _accent_t = "#7f1d1d"
        _badge_bg = "#dc2626"
        _badge_tx = "#ffffff"
        _signal   = "PUT"
        _action   = f"Watch for breakdown BELOW ${plan['yest_low']:.2f} on elevated volume."
        _action_d = (
            f"If the first 5-min candle closes below OR Low with ≥2× volume, "
            f"bot enters a PUT. Strong bounce off the low = wait for confirmation."
        )
    else:
        _accent   = "#d97706"
        _accent_l = "#fef3c7"
        _accent_t = "#78350f"
        _badge_bg = "#d97706"
        _badge_tx = "#ffffff"
        _signal   = "WAIT"
        _action   = f"No directional lean. Range: ${plan['yest_low']:.2f} – ${plan['yest_high']:.2f}."
        _action_d = (
            "Mixed signals — let the ORB candle define direction before committing. "
            "Bot trades whichever side breaks with volume ≥200% normal."
        )

    _gap_sign  = "▲" if gap_pct >= 0 else "▼"
    _gap_color = "#16a34a" if gap_pct >= 0 else "#dc2626"

    # ── Score bar ─────────────────────────────────────────────────────────────
    _meter_pct   = max(0, min(100, int((score + 4) / 8 * 100)))
    _meter_color = "#16a34a" if score >= 2 else "#dc2626" if score <= -2 else "#d97706"

    # ── Inside / outside range note ───────────────────────────────────────────
    _range_note = (
        "Inside yesterday's range — ORB will decide direction."
        if plan["inside_range"] else
        (f"Above yesterday's high (${plan['yest_high']:.2f}) — buyers in control pre-bell."
         if plan["pm_last"] > plan["yest_high"] else
         f"Below yesterday's low (${plan['yest_low']:.2f}) — sellers in control pre-bell.")
    )

    # ── Reasons as numbered list items ────────────────────────────────────────
    _reason_items = "".join(
        f'<div style="display:flex;gap:10px;padding:6px 0;'
        f'border-bottom:1px solid #f3f4f6">'
        f'<span style="font-size:.72rem;font-weight:700;color:{_accent};'
        f'min-width:18px;padding-top:1px">{i}.</span>'
        f'<span style="font-size:.78rem;color:#374151;line-height:1.5">{r}</span>'
        f'</div>'
        for i, r in enumerate(plan["reasons"], 1)
    )

    # ── Key levels rows ───────────────────────────────────────────────────────
    _level_rows = "".join(
        f'<tr>'
        f'<td style="padding:5px 12px;font-size:.74rem;font-weight:600;'
        f'color:#374151;white-space:nowrap;border-bottom:1px solid #f3f4f6">{k}</td>'
        f'<td style="padding:5px 12px;font-size:.74rem;color:#6b7280;'
        f'border-bottom:1px solid #f3f4f6">{v}</td>'
        f'</tr>'
        for k, v in plan["key_levels"].items()
    )

    # ── Shared inline style strings (no CSS classes — Streamlit drops <style>) ──
    _F  = "font-family:-apple-system,'Helvetica Neue',Arial,sans-serif"
    _S0 = f"{_F};border-radius:6px;overflow:hidden;border:1px solid #e5e7eb;margin-bottom:10px;box-shadow:0 2px 8px rgba(0,0,0,.08)"
    # masthead
    _S1 = "background:#111827;padding:10px 18px;display:flex;align-items:center;gap:10px;flex-wrap:wrap"
    _S_pub  = "font-size:.60rem;font-weight:800;letter-spacing:.18em;text-transform:uppercase;color:#9ca3af"
    _S_div  = "color:#4b5563;font-size:.85rem"
    _S_ts   = "font-size:.68rem;color:#6b7280;letter-spacing:.04em"
    _S_badge= f"background:{_badge_bg};color:{_badge_tx};font-size:.60rem;font-weight:800;letter-spacing:.12em;text-transform:uppercase;padding:3px 10px;border-radius:3px;margin-left:auto"
    # headline
    _S2     = f"background:#1f2937;padding:12px 18px 10px;border-bottom:3px solid {_accent}"
    _S_hll  = f"font-size:.60rem;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:{_accent};margin-bottom:4px"
    _S_hlt  = "font-size:1.0rem;font-weight:700;color:#f9fafb;line-height:1.3"
    _S_hls  = "font-size:.72rem;color:#9ca3af;margin-top:4px"
    # kpi row
    _S3     = "display:grid;grid-template-columns:repeat(4,1fr);border-bottom:1px solid #e5e7eb;background:#fff"
    _S_kpi  = "padding:10px 14px;border-right:1px solid #f3f4f6"
    _S_kpil = "font-size:.58rem;font-weight:700;letter-spacing:.10em;text-transform:uppercase;color:#9ca3af;margin-bottom:3px"
    _S_kpiv = "font-size:.90rem;font-weight:700;color:#111827"
    # section
    _S_sec  = "padding:12px 18px;border-bottom:1px solid #f3f4f6;background:#fff"
    _S_secl = "font-size:.58rem;font-weight:800;letter-spacing:.14em;text-transform:uppercase;color:#9ca3af;margin-bottom:8px;padding-bottom:5px;border-bottom:1px solid #f3f4f6"
    # signal box
    _S_sig  = f"background:{_accent_l};border-left:4px solid {_accent};border-radius:0 4px 4px 0;padding:10px 14px;margin-top:6px"
    _S_sigh = f"font-size:.70rem;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:{_accent_t};margin-bottom:3px"
    _S_sigb = "font-size:.76rem;color:#374151;line-height:1.5"
    # reason row
    _S_rrow = "display:flex;gap:10px;padding:6px 0;border-bottom:1px solid #f3f4f6"
    _S_rnum = f"font-size:.72rem;font-weight:700;color:{_accent};min-width:18px;padding-top:1px"
    _S_rtxt = "font-size:.76rem;color:#374151;line-height:1.5"
    # meter
    _S_mlbl = "display:flex;justify-content:space-between;font-size:.58rem;color:#9ca3af;margin-bottom:4px"
    _S_mtrk = "background:#e5e7eb;border-radius:2px;height:6px;overflow:hidden"
    _S_mfil = f"width:{_meter_pct}%;height:100%;background:{_meter_color};border-radius:2px"
    _S_mscr = f"font-size:.66rem;font-weight:700;color:{_meter_color};margin-top:4px;text-align:right"

    # ── Build reason items with inline styles ─────────────────────────────────
    _reason_items = "".join(
        f'<div style="{_S_rrow}">'
        f'<span style="{_S_rnum}">{i}.</span>'
        f'<span style="{_S_rtxt}">{r}</span>'
        f'</div>'
        for i, r in enumerate(plan["reasons"], 1)
    )

    # ── Build key levels rows with inline styles ──────────────────────────────
    _S_td1 = "padding:5px 12px;font-size:.74rem;font-weight:600;color:#374151;white-space:nowrap;border-bottom:1px solid #f3f4f6"
    _S_td2 = "padding:5px 12px;font-size:.74rem;color:#6b7280;border-bottom:1px solid #f3f4f6"
    _level_rows = "".join(
        f'<tr><td style="{_S_td1}">{k}</td><td style="{_S_td2}">{v}</td></tr>'
        for k, v in plan["key_levels"].items()
    )

    st.markdown(
        f'<div style="{_S0}">'

        # MASTHEAD
        f'<div style="{_S1}">'
        f'<span style="{_S_pub}">Celo Trader</span>'
        f'<span style="{_S_div}">|</span>'
        f'<span style="{_S_pub};letter-spacing:.06em;font-weight:400">Market Intelligence</span>'
        f'<span style="{_S_div}">|</span>'
        f'<span style="{_S_ts}">{plan["generated_at"]} ET</span>'
        f'<span style="{_S_badge}">{_signal} SIGNAL</span>'
        f'</div>'

        # HEADLINE
        f'<div style="{_S2}">'
        f'<div style="{_S_hll}">{ticker} &middot; Daily Trade Brief</div>'
        f'<div style="{_S_hlt}">{plan["bias_short"]}</div>'
        f'<div style="{_S_hls}">{_range_note}</div>'
        f'</div>'

        # KPI ROW
        f'<div style="{_S3}">'
        f'<div style="{_S_kpi}"><div style="{_S_kpil}">Pre-Market</div><div style="{_S_kpiv}">${plan["pm_last"]:.2f}</div></div>'
        f'<div style="{_S_kpi}"><div style="{_S_kpil}">Gap</div><div style="{_S_kpiv};color:{_gap_color}">{_gap_sign} {abs(gap_pct):.2f}%</div></div>'
        f'<div style="{_S_kpi}"><div style="{_S_kpil}">Prev Close</div><div style="{_S_kpiv}">${plan["yest_close"]:.2f}</div></div>'
        f'<div style="{_S_kpi};border-right:none"><div style="{_S_kpil}">Week Range</div><div style="{_S_kpiv};font-size:.78rem">${plan["week_low"]:.2f} &ndash; ${plan["week_high"]:.2f}</div></div>'
        f'</div>'

        # SIGNAL
        f'<div style="{_S_sec}">'
        f'<div style="{_S_secl}">09:30 Open Strategy</div>'
        f'<div style="{_S_sig}">'
        f'<div style="{_S_sigh}">{_signal} Setup</div>'
        f'<div style="{_S_sigb}"><strong>{_action}</strong><br>{_action_d}</div>'
        f'</div></div>'

        # ANALYSIS
        f'<div style="{_S_sec}">'
        f'<div style="{_S_secl}">Signal Analysis &mdash; {score:+d} / 4 factors {bias}</div>'
        f'{_reason_items}'
        f'<div style="margin-top:10px">'
        f'<div style="{_S_mlbl}"><span>Very Bearish</span><span>Neutral</span><span>Very Bullish</span></div>'
        f'<div style="{_S_mtrk}"><div style="{_S_mfil}"></div></div>'
        f'<div style="{_S_mscr}">Conviction: {score:+d}/4 &rarr; {bias}</div>'
        f'</div></div>'

        # KEY LEVELS
        f'<div style="{_S_sec};border-bottom:none">'
        f'<div style="{_S_secl}">Key Price Levels</div>'
        f'<table style="width:100%;border-collapse:collapse">{_level_rows}</table>'
        f'</div>'

        f'</div>',
        unsafe_allow_html=True,
    )

    # ── Dismiss ───────────────────────────────────────────────────────────────
    # FIX 2026-06-22: key was a hardcoded literal ("tp_dismiss"), so when the
    # Daily Brief page renders more than one ticker's plan in the same run
    # (the for-loop at the "brief" page call site), the second banner's
    # button collided with the first → StreamlitDuplicateElementKey crash.
    # Scoping the key to the ticker makes each banner's button unique.
    if st.button("Dismiss brief", key=f"tp_dismiss_{ticker}", type="secondary"):
        st.session_state["trade_plan_dismissed"] = True
        st.rerun()


# ── Live price ticker bar ─────────────────────────────────────────────────────
# Defined here (module level) so it can be called once AFTER all page branches.
# position:fixed CSS keeps it pinned to the bottom of the viewport on every page.

_TICKER_SYMBOLS = ["SPY", "QQQ", "AAPL", "NVDA", "TSLA", "AMC"]

@st.fragment(run_every=60)
def _price_ticker_bar():
    """
    Scrolling price bar pinned to the bottom of the viewport.
    Refreshes every 60 s via @st.fragment — one API call per refresh
    using get_snapshots() instead of 12 individual quote+bar calls.
    Falls back to session_state cache if the API is rate-limited.
    """
    _alpaca_tb, _ = get_clients()
    _items: list[str] = []

    # ONE batch call for all symbols — avoids hitting the free-tier 429 limit
    _snaps = _alpaca_tb.get_snapshots(_TICKER_SYMBOLS)

    # Merge live data into session_state cache; display cached data on failure
    for _sym in _TICKER_SYMBOLS:
        _snap = _snaps.get(_sym)
        if _snap and _snap.get("price", 0) > 0:
            # Live data available — update cache
            _px      = _snap["price"]
            _chg_pct = _snap["change_pct"]
            st.session_state[f"_tb_px_{_sym}"]  = _px
            st.session_state[f"_tb_chg_{_sym}"] = _chg_pct
        else:
            # Rate-limited or error — silently use last known values
            _px      = st.session_state.get(f"_tb_px_{_sym}", 0.0)
            _chg_pct = st.session_state.get(f"_tb_chg_{_sym}", 0.0)

        _arrow  = "▲" if _chg_pct >= 0 else "▼"
        _cls    = "ticker-up" if _chg_pct >= 0 else "ticker-dn"
        _sign   = "+" if _chg_pct >= 0 else ""
        _px_str  = f"${_px:.2f}" if _px else "—"
        _chg_str = f"{_sign}{_chg_pct:.2f}%" if _px else ""

        _items.append(
            f'<span class="ticker-item">'
            f'<span class="ticker-sym">{_sym}</span>'
            f'<span class="ticker-px">&nbsp;{_px_str}</span>'
            f'<span class="{_cls}">&nbsp;{_arrow} {_chg_str}</span>'
            f'</span>'
        )

    _inner = "".join(_items)
    st.markdown(
        f'<div class="ticker-wrap"><div class="ticker-track">'
        f'{_inner}{_inner}'   # duplicate for seamless infinite loop
        f'</div></div>',
        unsafe_allow_html=True,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 1: LIVE TRADING
# ═══════════════════════════════════════════════════════════════════════════════
if page == "live":
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
        # Keep pre-market (04:00+) and regular session bars; strip post-market (>20:00)
        # only to avoid runaway x-axis. Do NOT strip pre-market — the user wants it.
        if not _df_raw.empty:
            _session_mask = (
                (_df_raw["time"].dt.hour >= 4) & (_df_raw["time"].dt.hour < 20)
            )
            _filtered_raw = _df_raw[_session_mask].reset_index(drop=True)
            if not _filtered_raw.empty:
                _df_raw = _filtered_raw

        # ── Prepend yfinance pre-market bars (IEX free tier = 9:30–16:00 only) ──
        # Alpaca/IEX returns regular-session bars only on the free plan.  yfinance
        # is always free, always has pre-market (04:00–09:29 ET) for all US symbols.
        # Cache the fetch for 5 minutes in session_state to avoid rate-limiting
        # the dashboard's auto-refresh cycle (which re-renders every 10–30 s).
        try:
            import yfinance as _yf_pm
            _pm_cache_key = f"_pm_bars_{_fetch_sym}"
            _pm_cache_ts_key = f"_pm_bars_ts_{_fetch_sym}"
            _pm_ttl = 300   # seconds — pre-market bars don't change, so 5 min is safe
            _now_ts = _chart_time.time()
            _cached_pm = st.session_state.get(_pm_cache_key)
            _cached_pm_ts = st.session_state.get(_pm_cache_ts_key, 0)
            if _cached_pm is None or (_now_ts - _cached_pm_ts) > _pm_ttl:
                # Fetch fresh pre-market bars from yfinance
                _yf_pm_df = _yf_pm.download(
                    _fetch_sym, period="2d", interval="5m",
                    progress=False, auto_adjust=True, prepost=True,
                )
                if not _yf_pm_df.empty:
                    if isinstance(_yf_pm_df.columns, pd.MultiIndex):
                        _yf_pm_df.columns = _yf_pm_df.columns.get_level_values(0)
                    _yf_pm_df = _yf_pm_df.rename(columns={
                        "Open": "open", "High": "high", "Low": "low",
                        "Close": "close", "Volume": "volume",
                    })
                    _yf_pm_df.index.name = "time"
                    _yf_pm_df = _yf_pm_df.reset_index()
                    if hasattr(_yf_pm_df["time"].dtype, "tz") and _yf_pm_df["time"].dt.tz is not None:
                        _yf_pm_df["time"] = (
                            _yf_pm_df["time"]
                            .dt.tz_convert("America/New_York")
                            .dt.tz_localize(None)
                        )
                    # Keep ONLY pre-market bars (04:00–09:29 ET) from the latest date
                    _yf_latest = _yf_pm_df["time"].dt.date.max()
                    _pm_only = _yf_pm_df[
                        (_yf_pm_df["time"].dt.date == _yf_latest) &
                        (
                            (_yf_pm_df["time"].dt.hour < 9) |
                            ((_yf_pm_df["time"].dt.hour == 9) &
                             (_yf_pm_df["time"].dt.minute < 30))
                        )
                    ][["time", "open", "high", "low", "close", "volume"]].copy()
                    st.session_state[_pm_cache_key]    = _pm_only
                    st.session_state[_pm_cache_ts_key] = _now_ts
                    _cached_pm = _pm_only
                else:
                    st.session_state[_pm_cache_ts_key] = _now_ts  # back-off even on empty

            if _cached_pm is not None and not _cached_pm.empty and not _df_raw.empty:
                _today_date = _df_raw["time"].dt.date.max()
                _pm_today = _cached_pm[_cached_pm["time"].dt.date == _today_date]
                if not _pm_today.empty:
                    _df_raw = (
                        pd.concat([_pm_today, _df_raw], ignore_index=True)
                        .sort_values("time")
                        .drop_duplicates("time")
                        .reset_index(drop=True)
                    )
        except Exception as _pm_ex:
            import logging as _pm_log
            _pm_log.getLogger("celo_trader.dashboard").warning(
                "Pre-market yfinance prepend failed for %s: %s", _fetch_sym, _pm_ex
            )

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
            # Strip post-market only (>20:00); keep pre-market bars if present
            if not _df1m_raw.empty:
                _df1m_raw = _df1m_raw[
                    (_df1m_raw["time"].dt.hour >= 4) & (_df1m_raw["time"].dt.hour < 20)
                ].reset_index(drop=True)

            # Prepend yfinance pre-market 1m bars (IEX free = regular session only).
            # Cached for 5 minutes in session_state to avoid rate-limiting.
            try:
                import yfinance as _yf_pm1
                import time as _chart_time1
                _pm1_cache_key    = f"_pm1m_bars_{_sym1m}"
                _pm1_cache_ts_key = f"_pm1m_bars_ts_{_sym1m}"
                _pm1_ttl  = 300
                _now_ts1  = _chart_time1.time()
                _cached_pm1    = st.session_state.get(_pm1_cache_key)
                _cached_pm1_ts = st.session_state.get(_pm1_cache_ts_key, 0)
                if _cached_pm1 is None or (_now_ts1 - _cached_pm1_ts) > _pm1_ttl:
                    _yf1m_df = _yf_pm1.download(
                        _sym1m, period="2d", interval="1m",
                        progress=False, auto_adjust=True, prepost=True,
                    )
                    if not _yf1m_df.empty:
                        if isinstance(_yf1m_df.columns, pd.MultiIndex):
                            _yf1m_df.columns = _yf1m_df.columns.get_level_values(0)
                        _yf1m_df = _yf1m_df.rename(columns={
                            "Open": "open", "High": "high", "Low": "low",
                            "Close": "close", "Volume": "volume",
                        })
                        _yf1m_df.index.name = "time"
                        _yf1m_df = _yf1m_df.reset_index()
                        if hasattr(_yf1m_df["time"].dtype, "tz") and _yf1m_df["time"].dt.tz is not None:
                            _yf1m_df["time"] = (
                                _yf1m_df["time"]
                                .dt.tz_convert("America/New_York")
                                .dt.tz_localize(None)
                            )
                        _yf1m_latest = _yf1m_df["time"].dt.date.max()
                        _pm1m_only = _yf1m_df[
                            (_yf1m_df["time"].dt.date == _yf1m_latest) &
                            (
                                (_yf1m_df["time"].dt.hour < 9) |
                                ((_yf1m_df["time"].dt.hour == 9) &
                                 (_yf1m_df["time"].dt.minute < 30))
                            )
                        ][["time", "open", "high", "low", "close", "volume"]].copy()
                        st.session_state[_pm1_cache_key]    = _pm1m_only
                        st.session_state[_pm1_cache_ts_key] = _now_ts1
                        _cached_pm1 = _pm1m_only
                    else:
                        st.session_state[_pm1_cache_ts_key] = _now_ts1

                if _cached_pm1 is not None and not _cached_pm1.empty and not _df1m_raw.empty:
                    _1m_date = _df1m_raw["time"].dt.date.max()
                    _pm1m_today = _cached_pm1[_cached_pm1["time"].dt.date == _1m_date]
                    if not _pm1m_today.empty:
                        _df1m_raw = (
                            pd.concat([_pm1m_today, _df1m_raw], ignore_index=True)
                            .sort_values("time")
                            .drop_duplicates("time")
                            .reset_index(drop=True)
                        )
            except Exception as _pm1_ex:
                import logging as _pm1_log
                _pm1_log.getLogger("celo_trader.dashboard").warning(
                    "1m pre-market yfinance prepend failed for %s: %s", _sym1m, _pm1_ex
                )

            df_1m = _add_indicators(_df1m_raw)
        else:
            df_1m = df_5m.copy()
    except Exception:
        df_1m = df_5m.copy()

    # FIX 2026-06-22: _raw1m can be truthy but parse to an EMPTY frame (e.g.
    # malformed/zero-length bar payload from _b2d) — that path fell through
    # both branches above with no safety net, unlike df_5m (which always
    # gets the NaN-placeholder fallback a few lines up). An empty df_1m used
    # to just render an empty/odd chart; now that the Live Trading chart's
    # single-chart view is the default (Quad removed), this gap became the
    # visible "No bar data" error instead of being masked by Quad's other
    # tiles. Same fallback df_5m already uses elsewhere in this function.
    if df_1m is None or df_1m.empty:
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
            # FIX 2026-06-21: "Quad (4 Charts)" removed per direct request —
            # 4 small charts at once left no room for overlay detail, which
            # was the biggest reason the live chart looked cramped next to
            # TradingView. One big chart (below) now gets that room back.
            tf_sel = st.radio(
                "Timeframe",
                ["5m Chart", "1m Chart"],
                index=0,
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

        # ── Compose chart title — always embed the active ticker symbol ────
        _chart_title = (
            f"{_tk} · 5m{_session_tag}"
            if tf_sel == "5m Chart" else
            f"{_tk} · 1m{_session_tag}"
        )

        # ── TradingView-engine live chart (2026-06-21) ──────────────────────
        # Replaces the old Plotly single/Quad chart. One big chart + an
        # overlay checklist (like TradingView's own indicator list) instead
        # of 4 small charts with everything baked in. _render_orb_chart /
        # _orb_live_fig are left defined above, unused, in case either chart
        # is ever wanted back.
        def _build_live_trade_markers(chart_df: pd.DataFrame, trades: list,
                                       show_sim_trades: bool) -> list[dict]:
            """
            Plain-data version of the BUY/SELL marker math used by the old
            Plotly chart (_orb_live_fig) — produces dicts the chart renderer
            can draw directly, with zero trade math inside lightweight_chart.py
            itself (same convention as render_strategy_chart's vwap/or_high
            args). Real trades always show; SIM/ghost trades only show when
            show_sim_trades (the old "Simulation Mode" checkbox) is on.
            """
            out: list[dict] = []
            _today_s2 = date.today().isoformat()
            for _t in (trades or []):
                try:
                    _et_raw = str(_t.get("entry_time") or "")
                    _is_sim = str(_t.get("contract_symbol", "")).startswith("SIM_")
                    if _is_sim and not show_sim_trades:
                        continue
                    if not _et_raw:
                        continue
                    _et_parsed = pd.to_datetime(_et_raw)
                    if _et_parsed.tzinfo is not None:
                        _et_parsed = _et_parsed.tz_convert("America/New_York").tz_localize(None)
                    if not _is_sim and _et_parsed.date().isoformat() != _today_s2:
                        continue

                    _ep_t = float(_t.get("entry_price") or 0)
                    if _ep_t <= 0:
                        continue
                    _strat_id  = str(_t.get("strategy_id") or "INST_ORB")
                    _risk_cap  = 50.0
                    _contracts = max(1, int(_risk_cap / max(_ep_t * 0.30, 0.01)))
                    _opt_type  = str(_t.get("option_type") or "").upper() or "CALL"
                    _strike    = float(_t.get("strike") or round(_ep_t))

                    if _is_sim:
                        _underlying_entry = _ep_t
                        _cached_opt = _t.get("opt_entry_px")
                        _opt_entry_px_v = float(_cached_opt) if _cached_opt else _bs_price(
                            _ep_t, _strike, _et_parsed.to_pydatetime(), _opt_type == "CALL")
                    else:
                        _opt_entry_px_v = _ep_t
                        _underlying_entry = _ep_t
                        try:
                            _idx_e = (chart_df["time"] - _et_parsed).abs().idxmin()
                            _underlying_entry = float(chart_df.loc[_idx_e, "close"])
                        except Exception:
                            pass

                    out.append({
                        "time": int(_et_parsed.timestamp()),
                        "side": "buy",
                        "price": _underlying_entry,
                        "color": "#3b82f6",
                        "label": f"BUY ${_ep_t:.2f}",
                        "tag": "● BUY",
                        "lines": [
                            f"Strategy: {_strat_id}",
                            f"Contracts: {_contracts}",
                            f"Underlying: ${_underlying_entry:.2f}",
                            f"Option: {_opt_type} ${_strike:.0f} | ${_opt_entry_px_v:.2f}",
                            f"Initial Risk: ~${_risk_cap:.0f}",
                        ],
                    })

                    _xt_raw = str(_t.get("exit_time") or "")
                    _xp_raw = _t.get("exit_price")
                    _has_exit = (
                        bool(_xt_raw) and len(_xt_raw) > 5
                        and _xt_raw not in ("None", "nan", "")
                        and _xp_raw not in (None, 0, 0.0, "0", "0.0", "None")
                    )
                    if not _has_exit:
                        continue

                    _xt_parsed = pd.to_datetime(_xt_raw)
                    if _xt_parsed.tzinfo is not None:
                        _xt_parsed = _xt_parsed.tz_convert("America/New_York").tz_localize(None)
                    _xp  = float(_xp_raw)
                    _pnl = float(_t.get("realized_pnl") or 0.0)
                    _exit_reason = str(
                        _t.get("exit_reason") or _t.get("close_reason") or
                        ("TP hit" if _pnl > 0 else "SL hit" if _pnl < 0 else "manual")
                    )

                    if _is_sim:
                        _underlying_exit = _xp
                        _cached_exit_opt = _t.get("opt_exit_px")
                        _opt_exit_px_v = float(_cached_exit_opt) if _cached_exit_opt else _bs_price(
                            _xp, _strike, _xt_parsed.to_pydatetime(), _opt_type == "CALL")
                    else:
                        _opt_exit_px_v = _xp
                        _underlying_exit = _xp
                        try:
                            _idx_x = (chart_df["time"] - _xt_parsed).abs().idxmin()
                            _underlying_exit = float(chart_df.loc[_idx_x, "close"])
                        except Exception:
                            pass

                    _pnl_pct = (((_opt_exit_px_v - _opt_entry_px_v) / _opt_entry_px_v * 100)
                                if _opt_entry_px_v > 0 else 0.0)
                    _pnl_str = f"+${_pnl:.0f}" if _pnl >= 0 else f"-${abs(_pnl):.0f}"

                    out.append({
                        "time": int(_xt_parsed.timestamp()),
                        "side": "sell",
                        "price": _underlying_exit,
                        "color": "#BB6BD9",
                        "label": f"SELL {_pnl_str}",
                        "tag": "● SELL",
                        "lines": [
                            f"Exit Type: {_exit_reason}",
                            f"Underlying: ${_underlying_exit:.2f}",
                            f"Option: ${_opt_entry_px_v:.2f} → ${_opt_exit_px_v:.2f}",
                            f"P&L %: {_pnl_pct:+.1f}%",
                            f"Net P&L: {_pnl_str}",
                        ],
                    })
                except Exception as _me2:
                    logger.debug("Live trade marker build error: %s", _me2)
                    continue
            return out

        # ── Overlay checklist — TradingView-style on/off toggles ───────────
        _ov1, _ov2, _ov3, _ov4, _ov5, _ov6 = st.columns(6)
        _show_vwap_ov    = _ov1.checkbox("VWAP",           value=True,  key="ov_vwap")
        _show_bands_ov   = _ov2.checkbox("VWAP σ Bands",   value=True,  key="ov_bands")
        _show_or_ov      = _ov3.checkbox("OR Zone",        value=True,  key="ov_or")
        _show_pos_ov     = _ov4.checkbox("Position Lines", value=True,  key="ov_pos")
        _show_markers_ov = _ov5.checkbox("Trade Markers",  value=True,  key="ov_markers")
        _show_swings_ov  = _ov6.checkbox("Swing Structure", value=False, key="ov_swings")

        if df_display is None or df_display.empty or len(df_display) < 2:
            st.error(
                f"⚠️ No bar data for {_tk}. "
                "IEX feed doesn't carry ETFs (SPY/QQQ) — yfinance fallback also "
                "unavailable. Check internet connection or Alpaca API key."
            )
        else:
            _or_inf_live = _get_or(df_display)
            _live_markers = _build_live_trade_markers(df_display, _today_trades, sim_mode)

            _live_swings = None
            if _show_swings_ov:
                try:
                    from strategy_router import _find_swings as _fs_live
                    _sw_raw = _fs_live(df_display, pivot_bars=2)
                    _live_swings = [{"idx": i, "price": float(p), "type": t} for i, p, t in _sw_raw]
                except Exception:
                    _live_swings = None

            _live_position_levels = None
            if _show_levels and _levels_on_chart_scale:
                _live_position_levels = {
                    "entry":  _ep_show,
                    "stop":   _sl_show,
                    "target": _tp_show,
                    "trail":  _tr_show if (_tr_show and _tr_show > _sl_show) else None,
                }

            from lightweight_chart import render_live_chart as _render_live_tv_chart
            _render_live_tv_chart(
                df_display, _tk, chart_title=_chart_title, height=540,
                or_high=(_or_inf_live["high"] if _or_inf_live else None),
                or_low=(_or_inf_live["low"] if _or_inf_live else None),
                position_levels=_live_position_levels,
                trade_markers=_live_markers,
                swing_points=_live_swings,
                show_vwap=_show_vwap_ov,
                show_vwap_bands=_show_bands_ov,
                show_or_zone=_show_or_ov,
                show_position_lines=_show_pos_ov,
                show_trade_markers=_show_markers_ov,
                show_swings=_show_swings_ov,
                show_volume_gate=sim_mode,
            )

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
# PAGE 2: PERFORMANCE
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "perf":
    import sqlite3 as _sq3
    from dateutil import parser as _dtp

    # ── Page header + Paper/Live toggle ──────────────────────────────────────
    _ph_left, _ph_right = st.columns([3, 1])
    with _ph_left:
        st.markdown(
            '<h2 style="margin:0 0 2px;font-size:1.35rem;font-weight:700;'
            'color:#111827;letter-spacing:-.01em">Performance</h2>'
            '<p style="margin:0;font-size:.78rem;color:#6b7280">'
            'All metrics calculated from your trade history</p>',
            unsafe_allow_html=True,
        )
    with _ph_right:
        _perf_mode_default = "Paper" if st.session_state.get("sim_mode", True) else "Live"
        _perf_mode = st.radio(
            "Mode",
            ["Paper", "Live"],
            index=0 if _perf_mode_default == "Paper" else 1,
            horizontal=True,
            key="perf_mode_radio",
            label_visibility="collapsed",
        )
    _perf_paper = (_perf_mode == "Paper")

    # ── Pull closed trades — connect to the right DB directly ─────────────────
    # Config's get_db_path() reads from settings (paper_trading key), but the
    # perf page has its own toggle so we pick the path explicitly here.
    _perf_db_file = str(DB_PATH_PAPER if _perf_paper else DB_PATH_LIVE)
    try:
        with _sq3.connect(_perf_db_file) as _pc:
            _pc.row_factory = _sq3.Row
            _perf_rows = _pc.execute(
                "SELECT ticker, realized_pnl, entry_time, exit_time, "
                "strategy_id, contracts, entry_price "
                "FROM trades WHERE status='closed' AND realized_pnl IS NOT NULL "
                "ORDER BY exit_time ASC"
            ).fetchall()
        _perf_closed = [dict(r) for r in _perf_rows]
    except Exception:
        _perf_closed = []

    # ── Derived stats ──────────────────────────────────────────────────────────
    _pnls  = [r["realized_pnl"] for r in _perf_closed]
    _wins  = [p for p in _pnls if p > 0]
    _losses= [p for p in _pnls if p <= 0]
    _win_rate      = len(_wins) / len(_pnls) if _pnls else 0.0
    _avg_win       = sum(_wins)    / len(_wins)    if _wins    else 0.0
    _avg_loss      = sum(_losses)  / len(_losses)  if _losses  else 0.0
    _total_pnl     = sum(_pnls)
    _profit_factor = (sum(_wins) / abs(sum(_losses))) if _losses and sum(_losses) != 0 else 0.0

    # Running drawdown series (used for chart + max_dd metric)
    _dd_cum, _dd_peak, _dd_vals, _dd_labels = 0.0, 0.0, [], []
    for _r in _perf_closed:
        _dd_cum += float(_r.get("realized_pnl", 0) or 0)
        if _dd_cum > _dd_peak: _dd_peak = _dd_cum
        _dd_vals.append(-(_dd_peak - _dd_cum))
        _dd_labels.append(str(_r.get("exit_time", ""))[:10])
    _max_dd = abs(min(_dd_vals)) if _dd_vals else 0.0

    # Average hold time
    _hold_mins = []
    for _r in _perf_closed:
        try:
            if _r["entry_time"] and _r["exit_time"]:
                _et = _dtp.parse(str(_r["entry_time"]))
                _xt = _dtp.parse(str(_r["exit_time"]))
                _hold_mins.append(max(0.0, (_xt - _et).total_seconds() / 60))
        except Exception:
            pass
    _avg_hold = sum(_hold_mins) / len(_hold_mins) if _hold_mins else 0.0

    # Commission estimate ($0.65/contract/leg, 2 legs = $1.30 round-trip)
    _COMM_RT         = 1.30
    _total_contracts = sum(int(_r.get("contracts", 1) or 1) for _r in _perf_closed)
    _total_commission= _total_contracts * _COMM_RT
    _net_pnl         = _total_pnl - _total_commission
    _fee_drag        = (_total_commission / abs(_total_pnl) * 100) if _total_pnl != 0 else 0.0

    # R:R ratio
    _rr_str = "–"
    if _avg_loss != 0:
        _rr_str = f"1 : {abs(_avg_win / _avg_loss):.1f}"

    # Daily summaries + cumulative P&L — query the toggled DB directly so
    # Paper/Live switch actually changes the charts (get_daily_summaries() and
    # get_cumulative_pnl() use get_conn() which ignores the toggle).
    try:
        with _sq3.connect(_perf_db_file) as _ds_conn:
            _ds_conn.row_factory = _sq3.Row
            _ds_rows = _ds_conn.execute(
                "SELECT trade_date, total_pnl FROM daily_summary ORDER BY trade_date"
            ).fetchall()
        _summaries = [dict(r) for r in _ds_rows]
    except Exception:
        _summaries = []

    # Build cumulative P&L series (mirrors get_cumulative_pnl logic)
    _cum_pnl_series: list[dict] = []
    _cum_running = 0.0
    for _ds in _summaries:
        _cum_running += _ds["total_pnl"]
        _cum_pnl_series.append({"date": _ds["trade_date"], "cumulative_pnl": _cum_running})

    # Sharpe (annualised, from daily summaries)
    _sharpe_str = "–"
    if _summaries and len(_summaries) > 1:
        import numpy as _np
        _ds_vals = [s["total_pnl"] for s in _summaries]
        _std = _np.std(_ds_vals)
        if _std > 0:
            _sharpe_str = f"{(_np.mean(_ds_vals) / _std) * (252 ** 0.5):.2f}"

    # ── Shared card CSS (injected once per page render) ───────────────────────
    _mode_accent = "#2563eb" if _perf_paper else "#16a34a"
    _mode_label  = "PAPER"  if _perf_paper else "LIVE"
    st.markdown(f"""
    <style>
    .pf-card {{
        background:#ffffff;border:1px solid #e5e7eb;border-radius:12px;
        padding:16px 18px;box-shadow:0 1px 3px rgba(0,0,0,.06);
        margin-bottom:0;
    }}
    .pf-label {{
        font-size:.62rem;color:#9ca3af;text-transform:uppercase;
        letter-spacing:.08em;font-weight:600;margin-bottom:4px;
    }}
    .pf-value {{
        font-size:1.45rem;font-weight:700;color:#111827;line-height:1.1;
    }}
    .pf-sub {{
        font-size:.72rem;color:#6b7280;margin-top:3px;
    }}
    .pf-green {{ color:#16a34a !important; }}
    .pf-red   {{ color:#dc2626 !important; }}
    .pf-blue  {{ color:#2563eb !important; }}
    .pf-mode-badge {{
        display:inline-flex;align-items:center;gap:6px;
        background:{_mode_accent}18;color:{_mode_accent};
        font-size:.62rem;font-weight:700;letter-spacing:.08em;
        padding:3px 10px;border-radius:20px;border:1px solid {_mode_accent}40;
    }}
    .pf-section-head {{
        font-size:.68rem;font-weight:700;color:#374151;
        text-transform:uppercase;letter-spacing:.1em;
        border-left:3px solid {_mode_accent};padding-left:8px;
        margin:20px 0 10px;
    }}
    </style>
    <div style="display:flex;align-items:center;justify-content:flex-end;
                margin-bottom:14px">
      <span class="pf-mode-badge">● {_mode_label}</span>
    </div>""", unsafe_allow_html=True)

    # ── KPI card row (8 metrics) ──────────────────────────────────────────────
    def _kpi(label, value, sub="", color=""):
        clr = f'class="pf-value pf-{color}"' if color else 'class="pf-value"'
        return (
            f'<div class="pf-card" style="text-align:center">'
            f'<div class="pf-label">{label}</div>'
            f'<div {clr}>{value}</div>'
            + (f'<div class="pf-sub">{sub}</div>' if sub else "")
            + "</div>"
        )

    _pnl_color = "green" if _total_pnl >= 0 else "red"
    _pf_color  = "green" if _profit_factor >= 1.0 else "red"
    _wr_color  = "green" if _win_rate >= 0.5 else "red"

    _k1,_k2,_k3,_k4,_k5,_k6,_k7,_k8 = st.columns(8)
    _k1.markdown(_kpi("Trades",       str(len(_pnls))),            unsafe_allow_html=True)
    _k2.markdown(_kpi("Win Rate",     f"{_win_rate*100:.1f}%",     color=_wr_color), unsafe_allow_html=True)
    _k3.markdown(_kpi("Avg Win",      f"${_avg_win:.2f}",          color="green"),   unsafe_allow_html=True)
    _k4.markdown(_kpi("Avg Loss",     f"${abs(_avg_loss):.2f}",    color="red"),     unsafe_allow_html=True)
    _k5.markdown(_kpi("Profit Factor",f"{_profit_factor:.2f}",     color=_pf_color), unsafe_allow_html=True)
    _k6.markdown(_kpi("Max Drawdown", f"${_max_dd:.2f}",           color="red"),     unsafe_allow_html=True)
    _k7.markdown(_kpi("Avg Hold",     f"{_avg_hold:.0f}m",         sub="target <45m"), unsafe_allow_html=True)
    _k8.markdown(_kpi("R:R",          _rr_str,                     sub="(avg win/loss)"), unsafe_allow_html=True)

    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

    # ── P&L flow (gross → fees → net → fee drag) ─────────────────────────────
    _gross_clr = "green" if _total_pnl >= 0 else "red"
    _net_clr   = "green" if _net_pnl   >= 0 else "red"
    _fd_clr    = "red"   if _fee_drag  > 10 else "green"
    _f1,_f2,_f3,_f4 = st.columns([3,2,3,2])
    _f1.markdown(_kpi("Gross P&L",    f"${_total_pnl:+.2f}",        color=_gross_clr), unsafe_allow_html=True)
    _f2.markdown(_kpi("Est. Fees",    f"-${_total_commission:.2f}",  sub="$1.30/contract"), unsafe_allow_html=True)
    _f3.markdown(_kpi("Net P&L",      f"${_net_pnl:+.2f}",          color=_net_clr),   unsafe_allow_html=True)
    _f4.markdown(_kpi("Fee Drag",     f"{_fee_drag:.1f}%",           sub="<10% = healthy", color=_fd_clr), unsafe_allow_html=True)

    st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)

    # ── Charts row 1: Equity Curve + P&L Calendar ────────────────────────────
    st.markdown('<div class="pf-section-head">Equity &amp; Daily P&amp;L</div>', unsafe_allow_html=True)
    _cc1, _cc2 = st.columns([3, 2])

    with _cc1:
        if _cum_pnl_series:
            df_curve = pd.DataFrame(_cum_pnl_series)
            df_curve["account_value"] = STARTING_CAPITAL + df_curve["cumulative_pnl"]
            _cv_total = df_curve["cumulative_pnl"].iloc[-1]
            _cv_pct   = _cv_total / STARTING_CAPITAL * 100
            _cv_sign  = "+" if _cv_total >= 0 else ""
            _cv_clr   = "#16a34a" if _cv_total >= 0 else "#dc2626"
            _cv_line  = "#2563eb"

            fig_curve = go.Figure()
            fig_curve.add_trace(go.Scatter(
                x=df_curve["date"], y=df_curve["account_value"],
                mode="lines",
                line=dict(color=_cv_line, width=2.5),
                fill="tozeroy",
                fillcolor="rgba(37,99,235,0.06)",
                name="Account Value",
                hovertemplate="$%{y:,.2f}<extra></extra>",
            ))
            fig_curve.add_hline(
                y=STARTING_CAPITAL, line_color="#d1d5db",
                line_dash="dash", line_width=1,
                annotation_text=f"Start ${STARTING_CAPITAL:,.0f}",
                annotation_font_size=9, annotation_font_color="#9ca3af",
            )
            fig_curve.update_layout(
                template="plotly_white",
                paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
                height=220,
                margin=dict(l=8, r=8, t=8, b=8),
                font=dict(family="Inter,sans-serif", color="#374151", size=10),
                yaxis=dict(tickprefix="$", gridcolor="#f3f4f6",
                           tickfont=dict(color="#6b7280", size=9), zeroline=False),
                xaxis=dict(gridcolor="#f9fafb", tickfont=dict(color="#6b7280", size=9)),
                showlegend=False, hovermode="x unified",
            )
            st.markdown(
                f'<div class="pf-card" style="padding:12px 14px">'
                f'<div style="display:flex;justify-content:space-between;'
                f'align-items:baseline;margin-bottom:8px">'
                f'<span style="font-size:.65rem;color:#9ca3af;font-weight:600;'
                f'text-transform:uppercase;letter-spacing:.08em">Equity Curve</span>'
                f'<span style="font-size:.85rem;font-weight:700;color:{_cv_clr}">'
                f'{_cv_sign}${_cv_total:,.2f} &nbsp;'
                f'<span style="font-size:.72rem;font-weight:500">'
                f'{_cv_sign}{_cv_pct:.1f}%</span></span></div>',
                unsafe_allow_html=True,
            )
            st.plotly_chart(fig_curve, use_container_width=True)
            st.markdown(
                f'<div style="display:flex;gap:16px;padding:8px 0 4px">'
                f'<span style="font-size:.68rem;color:#6b7280">'
                f'R:R <b style="color:#111827">{_rr_str}</b></span>'
                f'<span style="font-size:.68rem;color:#6b7280">'
                f'Sharpe <b style="color:#111827">{_sharpe_str}</b></span>'
                f'<span style="font-size:.68rem;color:#6b7280">'
                f'Net <b style="color:{_cv_clr}">{_cv_sign}${_cv_total:,.0f}</b></span>'
                f'</div></div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<div class="pf-card" style="text-align:center;padding:40px 14px">'
                '<div class="pf-label">Equity Curve</div>'
                '<div class="pf-sub">No trade history yet</div></div>',
                unsafe_allow_html=True,
            )

    with _cc2:
        if _summaries and len(_summaries) > 0:
            import calendar as _cal_mod, datetime as _dt_mod
            df_cal = pd.DataFrame(_summaries)
            df_cal["trade_date"] = pd.to_datetime(df_cal["trade_date"])
            _lp = df_cal["trade_date"].max().to_period("M")
            _dm = df_cal[df_cal["trade_date"].dt.to_period("M") == _lp]
            _ml = _dm["trade_date"].iloc[0].strftime("%b %Y")
            _dp = {int(r["trade_date"].day): float(r["total_pnl"]) for _, r in _dm.iterrows()}
            _yr, _mo = _lp.year, _lp.month
            _fw, _nd = _cal_mod.monthrange(_yr, _mo)
            _cb = "box-sizing:border-box;min-width:0;overflow:hidden;text-align:center;"
            _ch = "".join(
                f'<div style="{_cb}color:#9ca3af;font-size:.52rem;padding:2px 0;'
                f'font-weight:600;letter-spacing:.04em">{d}</div>'
                for d in ["M","T","W","T","F"]
            )
            _cells = f'<div style="{_cb}"></div>' * min(_fw, 4)
            for _d in range(1, _nd + 1):
                if _dt_mod.date(_yr, _mo, _d).weekday() > 4: continue
                _pv = _dp.get(_d)
                if _pv is not None:
                    if _pv >= 0:
                        _bg, _fc, _sg = "rgba(22,163,74,.15)", "#16a34a", "+"
                    else:
                        _bg, _fc, _sg = "rgba(220,38,38,.12)", "#dc2626", ""
                    _cells += (
                        f'<div style="{_cb}aspect-ratio:1;border-radius:4px;'
                        f'background:{_bg};color:{_fc};display:flex;flex-direction:column;'
                        f'align-items:center;justify-content:center;padding:2px;">'
                        f'<span style="font-size:.52rem;font-weight:700;opacity:.7">{_d}</span>'
                        f'<span style="font-size:.54rem;font-weight:700">'
                        f'{_sg}${abs(_pv):.0f}</span></div>'
                    )
                else:
                    _cells += (
                        f'<div style="{_cb}aspect-ratio:1;border-radius:4px;'
                        f'background:#f3f4f6;display:flex;align-items:center;'
                        f'justify-content:center;color:#d1d5db;font-size:.52rem">'
                        f'{_d}</div>'
                    )
            st.markdown(f"""
            <div class="pf-card" style="padding:12px 14px">
              <div style="font-size:.65rem;color:#9ca3af;font-weight:600;
                          text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px">
                P&amp;L Calendar — {_ml}</div>
              <div style="display:grid;grid-template-columns:repeat(5,minmax(0,1fr));
                          gap:2px">{_ch}{_cells}</div>
            </div>""", unsafe_allow_html=True)
        else:
            st.markdown(
                '<div class="pf-card" style="text-align:center;padding:40px 14px">'
                '<div class="pf-label">P&amp;L Calendar</div>'
                '<div class="pf-sub">No completed trades yet</div></div>',
                unsafe_allow_html=True,
            )

    # ── Charts row 2: Drawdown + Ticker Breakdown ─────────────────────────────
    st.markdown('<div class="pf-section-head">Drawdown &amp; Ticker Performance</div>', unsafe_allow_html=True)
    _dc1, _dc2 = st.columns([3, 2])

    with _dc1:
        if _perf_closed and _dd_vals:
            _fig_dd = go.Figure()
            _fig_dd.add_trace(go.Scatter(
                x=list(range(len(_dd_vals))),
                y=_dd_vals,
                mode="lines",
                line=dict(color="#dc2626", width=2),
                fill="tozeroy",
                fillcolor="rgba(220,38,38,0.08)",
                hovertext=_dd_labels,
                hovertemplate="%{hovertext}<br>$%{y:.2f} below peak<extra></extra>",
            ))
            _fig_dd.add_hline(y=0, line_color="#e5e7eb", line_width=1)
            _fig_dd.update_layout(
                template="plotly_white",
                paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
                height=200,
                margin=dict(l=8, r=8, t=8, b=8),
                font=dict(family="Inter,sans-serif", color="#374151", size=10),
                yaxis=dict(tickprefix="$", gridcolor="#f9fafb",
                           tickfont=dict(color="#6b7280", size=9), zeroline=False),
                xaxis=dict(title=dict(text="Trade #", font=dict(size=9, color="#9ca3af")),
                           gridcolor="#f9fafb", tickfont=dict(color="#6b7280", size=9)),
                showlegend=False,
            )
            st.markdown(
                f'<div class="pf-card" style="padding:12px 14px">'
                f'<div style="display:flex;justify-content:space-between;'
                f'align-items:baseline;margin-bottom:8px">'
                f'<span style="font-size:.65rem;color:#9ca3af;font-weight:600;'
                f'text-transform:uppercase;letter-spacing:.08em">Drawdown</span>'
                f'<span style="font-size:.75rem;font-weight:700;color:#dc2626">'
                f'Peak −${_max_dd:.2f}</span></div>',
                unsafe_allow_html=True,
            )
            st.plotly_chart(_fig_dd, use_container_width=True)
            st.markdown("</div>", unsafe_allow_html=True)
        else:
            st.markdown(
                '<div class="pf-card" style="text-align:center;padding:40px 14px">'
                '<div class="pf-label">Drawdown</div>'
                '<div class="pf-sub">No trade history yet</div></div>',
                unsafe_allow_html=True,
            )

    with _dc2:
        if _perf_closed:
            _tk_map: dict = {}
            for _r in _perf_closed:
                _tk = _r.get("ticker") or "UNKNOWN"
                if _tk not in _tk_map:
                    _tk_map[_tk] = {"trades": 0, "wins": 0, "pnl": 0.0}
                _tk_map[_tk]["trades"] += 1
                _pv = float(_r.get("realized_pnl", 0) or 0)
                _tk_map[_tk]["pnl"] += _pv
                if _pv > 0: _tk_map[_tk]["wins"] += 1

            _sorted_tk = sorted(_tk_map.items(), key=lambda x: x[1]["pnl"], reverse=True)
            _best_tk   = _sorted_tk[-1] if _sorted_tk else (None, {})
            _worst_tk  = _sorted_tk[0]  if _sorted_tk else (None, {})

            _tk_rows_html = ""
            for _tk, _td in _sorted_tk:
                _tk_wr  = _td["wins"] / _td["trades"] if _td["trades"] else 0
                _tk_clr = "#16a34a" if _td["pnl"] >= 0 else "#dc2626"
                _tk_sign= "+" if _td["pnl"] >= 0 else ""
                _tk_rows_html += (
                    f'<tr style="border-bottom:1px solid #f3f4f6">'
                    f'<td style="padding:7px 8px;font-weight:700;color:#111827'
                    f';font-size:.78rem">{_tk}</td>'
                    f'<td style="padding:7px 8px;color:#6b7280;font-size:.75rem'
                    f';text-align:center">{_td["trades"]}</td>'
                    f'<td style="padding:7px 8px;color:#6b7280;font-size:.75rem'
                    f';text-align:center">{_tk_wr*100:.0f}%</td>'
                    f'<td style="padding:7px 8px;font-weight:700;color:{_tk_clr}'
                    f';font-size:.78rem;text-align:right">'
                    f'{_tk_sign}${abs(_td["pnl"]):.2f}</td></tr>'
                )

            st.markdown(f"""
            <div class="pf-card" style="padding:12px 14px">
              <div style="font-size:.65rem;color:#9ca3af;font-weight:600;
                          text-transform:uppercase;letter-spacing:.08em;margin-bottom:10px">
                Ticker Breakdown</div>
              <table style="width:100%;border-collapse:collapse">
                <thead>
                  <tr style="border-bottom:2px solid #e5e7eb">
                    <th style="text-align:left;padding:4px 8px;font-size:.62rem;
                               color:#9ca3af;font-weight:600">Ticker</th>
                    <th style="text-align:center;padding:4px 8px;font-size:.62rem;
                               color:#9ca3af;font-weight:600">Trades</th>
                    <th style="text-align:center;padding:4px 8px;font-size:.62rem;
                               color:#9ca3af;font-weight:600">W%</th>
                    <th style="text-align:right;padding:4px 8px;font-size:.62rem;
                               color:#9ca3af;font-weight:600">Net P&amp;L</th>
                  </tr>
                </thead>
                <tbody>{_tk_rows_html}</tbody>
              </table>
              <div style="display:flex;gap:8px;margin-top:12px;flex-wrap:wrap">
                <span style="background:#dcfce7;color:#15803d;font-size:.6rem;
                             font-weight:700;padding:3px 10px;border-radius:20px">
                  ⭐ {_best_tk[0]} ${_best_tk[1].get("pnl",0):+.2f}</span>
                <span style="background:#fee2e2;color:#dc2626;font-size:.6rem;
                             font-weight:700;padding:3px 10px;border-radius:20px">
                  ⚠️ {_worst_tk[0]} ${_worst_tk[1].get("pnl",0):+.2f}</span>
              </div>
            </div>""", unsafe_allow_html=True)
        else:
            st.markdown(
                '<div class="pf-card" style="text-align:center;padding:40px 14px">'
                '<div class="pf-label">Ticker Breakdown</div>'
                '<div class="pf-sub">No closed trades yet</div></div>',
                unsafe_allow_html=True,
            )

    # ── Open Positions ────────────────────────────────────────────────────────
    st.markdown('<div class="pf-section-head">Open Positions</div>', unsafe_allow_html=True)
    _open_trades_perf = get_open_trades()
    if not _open_trades_perf and LIVE_STATE.get("open_trade"):
        _open_trades_perf = [LIVE_STATE["open_trade"]]

    if _open_trades_perf:
        from risk import RiskManager as _RMperf
        _rmperf = _RMperf()
        _bot_perf = _read_bot_state()
        _bot_open_positions = _bot_perf.get("open_positions") or {}

        for open_trade in _open_trades_perf:
            ep_perf  = float(open_trade["entry_price"])
            sl_perf  = _rmperf.stop_loss_price(ep_perf)
            _is_sim_perf = str(open_trade.get("contract_symbol", "")).startswith("SIM_")
            _pdata_perf = _bot_open_positions.get(str(open_trade["id"]), {})
            cur_perf = None if _is_sim_perf else (
                _pdata_perf.get("current_option_price")
                if _pdata_perf else _bot_perf.get("current_option_price")
            )
            if cur_perf and cur_perf > 0:
                unreal = (cur_perf - ep_perf) * open_trade.get("contracts", 1) * 100
                _cur_sfx   = "" if _bot_perf.get("market_open") else " ·last"
                cur_str    = f"${cur_perf:.3f}{_cur_sfx}"
                unreal_str = f"{'+'if unreal>=0 else ''}${unreal:.2f}"
                unreal_clr = "#16a34a" if unreal >= 0 else "#dc2626"
            elif not _is_sim_perf:
                cur_str = f"${ep_perf:.3f}"; unreal_str = "+$0.00"; unreal_clr = "#9ca3af"
            else:
                cur_str = "–"; unreal_str = "–"; unreal_clr = "#9ca3af"

            pos_col, btn_col = st.columns([5, 1])
            with pos_col:
                st.markdown(
                    f'<div class="pf-card" style="padding:12px 16px">'
                    f'<div style="font-size:.68rem;font-weight:700;color:#374151;'
                    f'margin-bottom:8px">{open_trade.get("ticker","")} &nbsp;·&nbsp; '
                    f'{open_trade.get("option_type","").upper()}</div>'
                    f'<div style="display:grid;grid-template-columns:repeat(5,1fr);gap:8px">'
                    f'<div><div class="pf-label">Contract</div>'
                    f'<div style="font-size:.78rem;font-weight:600;color:#111827">'
                    f'{open_trade["contract_symbol"][:14]}</div></div>'
                    f'<div><div class="pf-label">Entry</div>'
                    f'<div style="font-size:.78rem;font-weight:600;color:#111827">'
                    f'${ep_perf:.3f}</div></div>'
                    f'<div><div class="pf-label">Current</div>'
                    f'<div style="font-size:.78rem;font-weight:600;color:#111827">'
                    f'{cur_str}</div></div>'
                    f'<div><div class="pf-label">Stop</div>'
                    f'<div style="font-size:.78rem;font-weight:600;color:#dc2626">'
                    f'${sl_perf:.3f}</div></div>'
                    f'<div><div class="pf-label">Unreal P&amp;L</div>'
                    f'<div style="font-size:.78rem;font-weight:700;color:{unreal_clr}">'
                    f'{unreal_str}</div></div>'
                    f'</div></div>',
                    unsafe_allow_html=True,
                )
            with btn_col:
                st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
                if st.button("Close", key=f"perf_close_btn_{open_trade['id']}",
                             use_container_width=True):
                    try:
                        manual_close_position()
                        st.success("✅ Close order sent")
                        st.rerun()
                    except Exception as _ce:
                        st.error(f"Close failed: {_ce}")
                if st.button("🔴 Panic", key=f"perf_panic_btn_{open_trade['id']}",
                             use_container_width=True, type="primary"):
                    try:
                        panic_close_all()
                        st.success("🔴 Panic close sent")
                        st.rerun()
                    except Exception as _pe:
                        st.error(f"Panic close failed: {_pe}")
    else:
        st.markdown(
            '<div class="pf-card" style="text-align:center;padding:20px;color:#6b7280;'
            'font-size:.82rem">No open positions — bot is scanning for signals.</div>',
            unsafe_allow_html=True,
        )

    # ── Strategy Breakdown ────────────────────────────────────────────────────
    st.markdown('<div class="pf-section-head">Strategy Breakdown</div>', unsafe_allow_html=True)
    if _perf_closed:
        _strat_map: dict = {}
        for _r in _perf_closed:
            _sid = _r.get("strategy_id") or "UNKNOWN"
            if _sid not in _strat_map:
                _strat_map[_sid] = {"trades": 0, "wins": 0, "pnl": 0.0, "holds": []}
            _strat_map[_sid]["trades"] += 1
            _pval = float(_r.get("realized_pnl", 0) or 0)
            _strat_map[_sid]["pnl"] += _pval
            if _pval > 0: _strat_map[_sid]["wins"] += 1
            try:
                if _r["entry_time"] and _r["exit_time"]:
                    _et2 = _dtp.parse(str(_r["entry_time"]))
                    _xt2 = _dtp.parse(str(_r["exit_time"]))
                    _strat_map[_sid]["holds"].append(
                        max(0.0, (_xt2 - _et2).total_seconds() / 60)
                    )
            except Exception:
                pass

        _sb_rows = ""
        for _i, (_sid, _sd) in enumerate(sorted(
            _strat_map.items(), key=lambda x: x[1]["pnl"], reverse=True
        )):
            _wr   = _sd["wins"] / _sd["trades"] if _sd["trades"] else 0
            _ah   = sum(_sd["holds"]) / len(_sd["holds"]) if _sd["holds"] else 0
            _comm = _sd["trades"] * _COMM_RT
            _net  = _sd["pnl"] - _comm
            _pc   = "#16a34a" if _sd["pnl"] >= 0 else "#dc2626"
            _nc   = "#16a34a" if _net        >= 0 else "#dc2626"
            _psign= "+" if _sd["pnl"] >= 0 else ""
            _nsign= "+" if _net        >= 0 else ""
            _bg   = "#fafafa" if _i % 2 == 0 else "#ffffff"
            _sb_rows += (
                f'<tr style="background:{_bg};border-bottom:1px solid #f3f4f6">'
                f'<td style="padding:8px 10px;font-weight:700;color:#111827;font-size:.78rem">{_sid}</td>'
                f'<td style="padding:8px 10px;text-align:center;color:#6b7280;font-size:.75rem">{_sd["trades"]}</td>'
                f'<td style="padding:8px 10px;text-align:center;color:#6b7280;font-size:.75rem">{_wr*100:.0f}%</td>'
                f'<td style="padding:8px 10px;text-align:right;font-weight:700;color:{_pc};font-size:.78rem">'
                f'{_psign}${abs(_sd["pnl"]):.2f}</td>'
                f'<td style="padding:8px 10px;text-align:right;color:#9ca3af;font-size:.72rem">-${_comm:.2f}</td>'
                f'<td style="padding:8px 10px;text-align:right;font-weight:700;color:{_nc};font-size:.78rem">'
                f'{_nsign}${abs(_net):.2f}</td>'
                f'<td style="padding:8px 10px;text-align:center;color:#6b7280;font-size:.72rem">{_ah:.0f}m</td>'
                f'</tr>'
            )

        st.markdown(f"""
        <div class="pf-card" style="padding:0;overflow:hidden">
          <table style="width:100%;border-collapse:collapse">
            <thead>
              <tr style="background:#f9fafb;border-bottom:2px solid #e5e7eb">
                <th style="text-align:left;padding:9px 10px;font-size:.62rem;color:#9ca3af;font-weight:700">Strategy</th>
                <th style="text-align:center;padding:9px 10px;font-size:.62rem;color:#9ca3af;font-weight:700">Trades</th>
                <th style="text-align:center;padding:9px 10px;font-size:.62rem;color:#9ca3af;font-weight:700">Win %</th>
                <th style="text-align:right;padding:9px 10px;font-size:.62rem;color:#9ca3af;font-weight:700">Gross</th>
                <th style="text-align:right;padding:9px 10px;font-size:.62rem;color:#9ca3af;font-weight:700">Fees</th>
                <th style="text-align:right;padding:9px 10px;font-size:.62rem;color:#9ca3af;font-weight:700">Net</th>
                <th style="text-align:center;padding:9px 10px;font-size:.62rem;color:#9ca3af;font-weight:700">Avg Hold</th>
              </tr>
            </thead>
            <tbody>{_sb_rows}</tbody>
          </table>
        </div>""", unsafe_allow_html=True)
    else:
        st.markdown(
            '<div class="pf-card" style="text-align:center;padding:24px;color:#6b7280;font-size:.82rem">'
            'No closed trades yet — strategy breakdown will appear here once trades complete.</div>',
            unsafe_allow_html=True,
        )

# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 3: RISK SETTINGS
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "settings":
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
# PAGE: DAILY BRIEF
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "brief":
    st.markdown(f"""
<div style="padding:0 0 8px 0;border-bottom:2px solid {T['border']};margin-bottom:14px">
  <span style="font-size:1.4rem;font-weight:800;color:{T['text']};
               font-family:'Syne',sans-serif;letter-spacing:-.015em">📋 Daily Brief</span>
  <span style="font-size:.72rem;color:{T['muted']};font-weight:500;margin-left:10px">
    Today's game plan · generated pre-market
  </span>
</div>
""", unsafe_allow_html=True)

    # ── Today's Scanner Universe ────────────────────────────────────────────────
    # Read from daily_universe.json (written by scanner after 9:30 full scan).
    # Falls back to scanner_state.json watchlist if the full scan hasn't run yet.
    try:
        from scanner import get_today_universe, DAILY_UNIVERSE_PATH, ANCHOR_TICKERS as _ANCHORS
        import json as _json
        from pathlib import Path as _Path
        from datetime import datetime as _dt_brief
        import pytz as _pytz_brief

        _et_brief   = _dt_brief.now(_pytz_brief.timezone("America/New_York"))
        _today_str  = _et_brief.strftime("%Y-%m-%d")

        # Try reading daily_universe.json directly for richest data
        _du_path = Path(BASE_DIR) / "daily_universe.json" if "BASE_DIR" in dir() else _Path(__file__).parent / "daily_universe.json"
        _du: dict = {}
        try:
            _du = _json.loads(_du_path.read_text())
        except Exception:
            pass

        _du_universe  = _du.get("universe", [])
        _du_date      = _du.get("date", "")
        _du_scored    = _du.get("scored", [])          # list of {ticker, score, ...}
        _scan_is_today = (_du_date == _today_str)
        _scan_tickers  = _du_universe if _scan_is_today else []

        # Fallback: scanner_state.json watchlist (rescored live)
        if not _scan_tickers:
            _ss_path = _Path(__file__).parent / "scanner_state.json"
            try:
                _ss = _json.loads(_ss_path.read_text())
                _scan_tickers = _ss.get("watchlist", [])
            except Exception:
                pass

        _score_map: dict = {}
        for _row in _du_scored:
            if isinstance(_row, dict) and "ticker" in _row:
                _score_map[_row["ticker"]] = _row.get("score", 0.0)

        if _scan_tickers:
            _scan_label = f"{'✅ Full scan complete' if _scan_is_today else '⏳ Pre-market watchlist'} · {_et_brief.strftime('%b %d, %Y')}"
            st.markdown(f"""
<div style="margin-bottom:16px;padding:12px 16px;border-radius:8px;
            background:{T['surface']};border:1px solid {T['border']}">
  <div style="font-size:.72rem;font-weight:700;color:{T['muted']};
              text-transform:uppercase;letter-spacing:.08em;margin-bottom:10px">
    🎯 Today's Universe — {_scan_label}
  </div>
  <div style="display:flex;flex-wrap:wrap;gap:8px">
""", unsafe_allow_html=True)
            _ticker_pills = ""
            for _i, _t in enumerate(_scan_tickers):
                _rank_color = "#1d4ed8" if _i == 0 else ("#0ea5e9" if _i < 3 else T['muted'])
                _score_str  = f" · {_score_map[_t]:.3f}" if _t in _score_map else ""
                _rank_badge = f"#{_i+1}"
                _ticker_pills += f"""
    <span style="display:inline-flex;align-items:center;gap:5px;padding:4px 10px;
                 border-radius:20px;background:{_rank_color}18;
                 border:1px solid {_rank_color}40;font-size:.82rem;font-weight:700;
                 color:{_rank_color}">
      <span style="font-size:.65rem;color:{_rank_color}99">{_rank_badge}</span>
      {_t}{_score_str}
    </span>"""
            st.markdown(_ticker_pills + "\n  </div>\n</div>", unsafe_allow_html=True)
        else:
            st.markdown(f"""
<div style="padding:12px 16px;border-radius:8px;background:{T['surface']};
            border:1px solid {T['border']};margin-bottom:16px">
  <div style="font-size:.82rem;color:{T['muted']}">
    ⏳ <strong>Scanner hasn't run yet today.</strong>
    The bot scans 140 stocks at 9:30 AM ET and picks the top movers with gap + RVOL.
    Start the bot before market open to see today's universe here.
  </div>
</div>
""", unsafe_allow_html=True)
    except Exception as _brief_scan_ex:
        st.caption(f"Scanner data unavailable: {_brief_scan_ex}")

    # ── Trade Plan Cards ────────────────────────────────────────────────────────
    _bp_data = st.session_state.get("trade_plan_data")
    if isinstance(_bp_data, dict) and _bp_data:
        for _bp_ticker, _bp_plan in _bp_data.items():
            if _bp_plan:
                _render_trade_plan_banner(_bp_plan)
    else:
        st.markdown(f"""
<div style="text-align:center;padding:40px 20px">
  <div style="font-size:2.5rem;margin-bottom:10px">📰</div>
  <div style="font-size:.95rem;font-weight:700;color:{T['text']}">No trade plans yet today</div>
  <div style="font-size:.78rem;color:{T['muted']};margin-top:5px">
    Detailed per-ticker plans are generated between 09:15–10:00 AM ET.<br>
    Make sure the bot is running during pre-market.
  </div>
</div>
""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 4: TRADE JOURNAL
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "journal":
    # ═══════════════════════════════════════════════════════════════════════════
    # PAGE 5: TRADE JOURNAL — modern, sleek, light mode
    # ═══════════════════════════════════════════════════════════════════════════

    # ── Fetch open + closed, merge ──────────────────────────────────────────────
    _journal_open   = get_open_trades()
    _journal_closed = get_all_trades(limit=200)
    _all_rows = [dict(t, _is_open=True)  for t in _journal_open] + \
                [dict(t, _is_open=False) for t in _journal_closed]

    # ── Page header ─────────────────────────────────────────────────────────────
    st.markdown(f"""
<div style="padding:0 0 8px 0;border-bottom:2px solid {T['border']};margin-bottom:14px">
  <span style="font-size:1.4rem;font-weight:800;color:{T['text']};
               font-family:'Syne',sans-serif;letter-spacing:-.015em">📓 Trade Journal</span>
  <span style="font-size:.72rem;color:{T['muted']};font-weight:500;margin-left:10px">
    Every trade logged · wins, losses &amp; lessons
  </span>
</div>
""", unsafe_allow_html=True)

    # ── Empty state ──────────────────────────────────────────────────────────────
    if not _all_rows:
        st.markdown(f"""
<div style="text-align:center;padding:60px 20px">
  <div style="font-size:2.5rem;margin-bottom:10px">📭</div>
  <div style="font-size:.95rem;font-weight:700;color:{T['text']}">No trades yet</div>
  <div style="font-size:.78rem;color:{T['muted']};margin-top:5px">
    Start the bot to see your trading history here.
  </div>
</div>
""", unsafe_allow_html=True)
    else:
        # ── 1. Build + clean DataFrame ───────────────────────────────────────────
        df_j = pd.DataFrame(_all_rows)
        # Dedup: same (entry_time, ticker, contract_symbol, status) across sessions
        df_j = df_j.drop_duplicates(
            subset=["entry_time", "ticker", "contract_symbol", "status"], keep="last"
        ).reset_index(drop=True)

        # Datetime formatting — format="mixed" handles μs and whole-second ISO strings
        df_j["entry_time"] = pd.to_datetime(df_j["entry_time"], format="mixed").dt.strftime("%m/%d %H:%M")
        df_j["exit_time"]  = (
            pd.to_datetime(df_j["exit_time"], format="mixed", errors="coerce")
            .dt.strftime("%m/%d %H:%M")
            .fillna("—")
        )
        _bs_open_pos = _read_bot_state().get("open_positions") or {}

        def _pnl_fmt(row: pd.Series) -> str:
            if not row["_is_open"]:
                return f"${row['realized_pnl']:+.2f}" if pd.notna(row["realized_pnl"]) else "—"
            _pdata  = _bs_open_pos.get(str(int(row["id"])), {})
            _cur_px = _pdata.get("current_option_price")
            _entry  = float(row.get("entry_price") or 0)
            _qty    = int(row.get("contracts") or 1)
            if _cur_px and _cur_px > 0 and _entry > 0:
                return f"~${(_cur_px - _entry) * _qty * 100:+.2f}"
            return "—"

        df_j["pnl_fmt"] = df_j.apply(_pnl_fmt, axis=1)
        df_j["result"]  = df_j.apply(
            lambda r: "🟡 OPEN" if r["_is_open"]
                      else ("✅ WIN" if r["realized_pnl"] > 0 else "❌ LOSS"),
            axis=1,
        )

        def _j_opt_px(row: pd.Series, price_col: str) -> str:
            try:
                px = float(row.get(price_col) or 0)
                if px <= 0: return "—"
                sym = str(row.get("contract_symbol", ""))
                if not sym.startswith("SIM_"): return f"${px:.2f}"
                time_col = "entry_time" if price_col == "entry_price" else "exit_time"
                t_raw = row.get(time_col, "")
                if not t_raw or t_raw == "—": return f"${px * 0.013:.2f}"
                bar_dt = pd.to_datetime(t_raw).to_pydatetime()
                strike = float(row.get("strike") or round(px))
                is_call = str(row.get("option_type", "call")).lower() == "call"
                return f"${_bs_price(px, strike, bar_dt, is_call):.2f}"
            except Exception:
                return "—"

        df_j["opt_entry"] = df_j.apply(lambda r: _j_opt_px(r, "entry_price"), axis=1)
        df_j["opt_exit"]  = df_j.apply(lambda r: _j_opt_px(r, "exit_price"),  axis=1)

        def _signal_short(row) -> str:
            er  = str(row.get("entry_reason") or "")
            sid = str(row.get("strategy_id") or "")
            if sid == "RECOVERED_UNTRACKED":
                return "Stage-1 Split" if er.lower().startswith("reconciliation") else "Legacy"
            er_l = er.lower()
            if "bullish" in er_l: return "Bullish"
            if "bearish" in er_l: return "Bearish"
            if "neutral" in er_l: return "Neutral"
            short = er.split("|")[0].strip()
            return short[:40] if short else "—"

        df_j["signal_short"] = df_j.apply(_signal_short, axis=1)

        def _safe_note(row_dict: dict) -> str:
            try:
                base_html = build_trade_note_html(row_dict)
            except Exception:
                base_html = "<span style='color:#888'>Position still open</span>"
            sid = str(row_dict.get("strategy_id") or "")
            er  = str(row_dict.get("entry_reason") or "")
            if sid == "RECOVERED_UNTRACKED" and er:
                provenance = (
                    f"<div style='font-size:.65rem;color:#aaa;margin-bottom:6px;"
                    f"padding:4px 6px;border-left:2px solid #555;"
                    f"border-radius:2px;white-space:normal;word-break:break-word'>"
                    f"<b>📋 Origin:</b> {er}</div>"
                )
                return provenance + base_html
            return base_html

        df_j["notes"] = df_j.apply(lambda r: _safe_note(r.to_dict()), axis=1)
        df_j["exit_reason_disp"] = (
            df_j["exit_reason"].fillna("—").astype(str)
            .str.replace(r"\s*\(held=[^)]*\)", "", regex=True)
        )

        # ── 2. KPI summary cards ─────────────────────────────────────────────
        _all_closed_j = df_j[df_j["realized_pnl"].notna()]
        _j_total_pnl  = _all_closed_j["realized_pnl"].sum()  if len(_all_closed_j) else 0.0
        _j_wins       = int((_all_closed_j["realized_pnl"] > 0).sum())
        _j_losses     = int((_all_closed_j["realized_pnl"] <= 0).sum())
        _j_win_rate   = (_j_wins / len(_all_closed_j) * 100) if len(_all_closed_j) else None
        _j_best       = _all_closed_j["realized_pnl"].max()  if len(_all_closed_j) else None
        _j_worst      = _all_closed_j["realized_pnl"].min()  if len(_all_closed_j) else None
        _j_avg        = _all_closed_j["realized_pnl"].mean() if len(_all_closed_j) else None
        _j_open_cnt   = len(_journal_open)

        _j_pnl_c  = "#16a34a" if _j_total_pnl >= 0 else "#dc2626"
        _j_pnl_s  = f"${_j_total_pnl:+.2f}"
        _j_wr_s   = f"{_j_win_rate:.0f}%" if _j_win_rate is not None else "—"
        _j_best_s = f"${_j_best:+.2f}"    if _j_best  is not None else "—"
        _j_wrst_s = f"${_j_worst:+.2f}"   if _j_worst is not None else "—"
        _j_avg_s  = f"${_j_avg:+.2f}"     if _j_avg   is not None else "—"
        _j_open_b = (
            f"&nbsp;<span style='background:#fef3c7;color:#92400e;font-size:.58rem;"
            f"font-weight:700;padding:1px 6px;border-radius:10px'>{_j_open_cnt} open</span>"
            if _j_open_cnt > 0 else ""
        )
        st.markdown(f"""
<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:14px">
  <div style="background:{T['surface']};border:1px solid {T['border']};border-radius:10px;
              padding:12px 14px;box-shadow:0 1px 3px rgba(0,0,0,.05)">
    <div style="font-size:.58rem;font-weight:700;color:{T['muted']};text-transform:uppercase;
                letter-spacing:.08em;margin-bottom:3px">Total P&amp;L</div>
    <div style="font-size:1.2rem;font-weight:800;color:{_j_pnl_c};
                font-family:'JetBrains Mono',monospace">{_j_pnl_s}</div>
    <div style="font-size:.56rem;color:{T['muted']};margin-top:2px">{len(_all_closed_j)} closed trades</div>
  </div>
  <div style="background:{T['surface']};border:1px solid {T['border']};border-radius:10px;
              padding:12px 14px;box-shadow:0 1px 3px rgba(0,0,0,.05)">
    <div style="font-size:.58rem;font-weight:700;color:{T['muted']};text-transform:uppercase;
                letter-spacing:.08em;margin-bottom:3px">Win Rate</div>
    <div style="font-size:1.2rem;font-weight:800;color:{T['text']};
                font-family:'JetBrains Mono',monospace">{_j_wr_s}</div>
    <div style="font-size:.56rem;color:{T['muted']};margin-top:2px">{_j_wins}W · {_j_losses}L</div>
  </div>
  <div style="background:{T['surface']};border:1px solid {T['border']};border-radius:10px;
              padding:12px 14px;box-shadow:0 1px 3px rgba(0,0,0,.05)">
    <div style="font-size:.58rem;font-weight:700;color:{T['muted']};text-transform:uppercase;
                letter-spacing:.08em;margin-bottom:3px">Best / Worst</div>
    <div style="font-size:1rem;font-weight:800;line-height:1.3">
      <span style="color:#16a34a;font-family:'JetBrains Mono',monospace">{_j_best_s}</span>
      <span style="color:{T['muted']};font-size:.65rem"> / </span>
      <span style="color:#dc2626;font-family:'JetBrains Mono',monospace">{_j_wrst_s}</span>
    </div>
    <div style="font-size:.56rem;color:{T['muted']};margin-top:2px">single trade extremes</div>
  </div>
  <div style="background:{T['surface']};border:1px solid {T['border']};border-radius:10px;
              padding:12px 14px;box-shadow:0 1px 3px rgba(0,0,0,.05)">
    <div style="font-size:.58rem;font-weight:700;color:{T['muted']};text-transform:uppercase;
                letter-spacing:.08em;margin-bottom:3px">Avg / Open</div>
    <div style="font-size:1.2rem;font-weight:800;color:{T['text']};
                font-family:'JetBrains Mono',monospace">{_j_avg_s}{_j_open_b}</div>
    <div style="font-size:.56rem;color:{T['muted']};margin-top:2px">per trade average</div>
  </div>
</div>
""", unsafe_allow_html=True)

        # ── 3. P&L Curve ─────────────────────────────────────────────────────
        _closed_for_chart = [
            r for r in _all_rows
            if not r["_is_open"] and r.get("realized_pnl") is not None
        ]
        if _closed_for_chart:
            import plotly.graph_objects as _go
            _sorted_trades = sorted(_closed_for_chart, key=lambda r: r.get("entry_time") or "")
            _cum_pnl, _cum_total, _trade_labels, _dot_colors, _dot_sizes = [], 0.0, [], [], []
            for _tr in _sorted_trades:
                _pval = float(_tr["realized_pnl"])
                _cum_total += _pval
                _cum_pnl.append(_cum_total)
                _tk  = _tr.get("ticker", "")
                _opt = str(_tr.get("option_type", "")).upper()
                _strat = str(_tr.get("strategy_id", "")).upper() or "—"
                _trade_labels.append(
                    f"<b>{_tk} {_opt}</b>  [{_strat}]"
                    f"<br>Trade P&L: <b>${_pval:+.2f}</b>"
                    f"<br>Running Total: <b>${_cum_total:+.2f}</b>"
                )
                _dot_colors.append("#22c55e" if _pval >= 0 else "#ef4444")
                # larger dot for bigger wins/losses
                _dot_sizes.append(max(7, min(14, 7 + abs(_pval) / 10)))

            _xs  = list(range(1, len(_cum_pnl) + 1))
            _fig_j = _go.Figure()

            # ── Gradient fill: green if net positive, red if negative ─────────
            _net      = _cum_pnl[-1] if _cum_pnl else 0
            _fill_clr = "rgba(34,197,94,0.12)" if _net >= 0 else "rgba(239,68,68,0.10)"
            _fill_neg = "rgba(239,68,68,0.08)"
            # Above-zero fill
            _fig_j.add_trace(_go.Scatter(
                x=_xs, y=_cum_pnl, mode="none", fill="tozeroy",
                fillcolor=_fill_clr, showlegend=False, hoverinfo="skip",
            ))

            # ── Line — single clean stroke, accent color ──────────────────────
            _line_clr = "#22c55e" if _net >= 0 else "#ef4444"
            _fig_j.add_trace(_go.Scatter(
                x=_xs, y=_cum_pnl,
                mode="lines",
                line=dict(color=_line_clr, width=2, shape="spline", smoothing=0.6),
                showlegend=False, hoverinfo="skip",
            ))

            # ── Trade dots — separate trace for per-dot coloring ──────────────
            _fig_j.add_trace(_go.Scatter(
                x=_xs, y=_cum_pnl,
                mode="markers",
                marker=dict(
                    color=_dot_colors,
                    size=_dot_sizes,
                    line=dict(color="#111827", width=1.5),
                    opacity=0.95,
                ),
                hovertext=_trade_labels,
                hoverinfo="text",
                showlegend=False,
            ))

            # ── Zero baseline ─────────────────────────────────────────────────
            _fig_j.add_hline(
                y=0,
                line=dict(color="rgba(156,163,175,0.4)", width=1, dash="dot"),
            )

            # ── Final P&L annotation ──────────────────────────────────────────
            if _cum_pnl:
                _jf   = _cum_pnl[-1]
                _jf_c = "#22c55e" if _jf >= 0 else "#ef4444"
                _fig_j.add_annotation(
                    x=len(_cum_pnl), y=_jf,
                    text=f"<b>${_jf:+.2f}</b>",
                    showarrow=False, xanchor="left", yanchor="middle",
                    font=dict(color=_jf_c, size=12,
                              family="-apple-system,'Helvetica Neue',Arial,sans-serif"),
                    xshift=10,
                )

            _fig_j.update_layout(
                height=200,
                margin=dict(l=2, r=70, t=4, b=2),
                paper_bgcolor="#111827",
                plot_bgcolor="#111827",
                showlegend=False,
                font=dict(color="#6b7280",
                          family="-apple-system,'Helvetica Neue',Arial,sans-serif",
                          size=10),
                xaxis=dict(
                    showgrid=True,
                    gridcolor="rgba(255,255,255,0.05)",
                    zeroline=False,
                    tickfont=dict(size=9, color="#6b7280"),
                    tickprefix="T",
                    linecolor="rgba(255,255,255,0.08)",
                    showline=True,
                ),
                yaxis=dict(
                    showgrid=True,
                    gridcolor="rgba(255,255,255,0.05)",
                    zeroline=False,
                    tickprefix="$",
                    tickfont=dict(size=9, color="#6b7280"),
                    linecolor="rgba(255,255,255,0.08)",
                    showline=True,
                ),
                hovermode="closest",
                hoverlabel=dict(
                    bgcolor="#1f2937",
                    bordercolor="#374151",
                    font=dict(color="#f9fafb", size=11,
                              family="-apple-system,'Helvetica Neue',Arial,sans-serif"),
                ),
            )

            # ── Chart header ──────────────────────────────────────────────────
            _wins_c  = sum(1 for r in _closed_for_chart if float(r["realized_pnl"]) >= 0)
            _loss_c  = len(_closed_for_chart) - _wins_c
            _wr_disp = f"{_wins_c}/{len(_closed_for_chart)}"
            st.markdown(
                f"<div style='background:#111827;border-radius:6px 6px 0 0;"
                f"padding:8px 14px 6px;display:flex;align-items:center;gap:16px;"
                f"border:1px solid rgba(255,255,255,0.07);border-bottom:none;"
                f"font-family:-apple-system,\"Helvetica Neue\",Arial,sans-serif'>"
                f"<span style='font-size:.60rem;font-weight:700;letter-spacing:.12em;"
                f"text-transform:uppercase;color:#6b7280'>P&amp;L Curve</span>"
                f"<span style='font-size:.68rem;color:#22c55e;font-weight:600'>"
                f"&#9679; {_wins_c} wins</span>"
                f"<span style='font-size:.68rem;color:#ef4444;font-weight:600'>"
                f"&#9679; {_loss_c} losses</span>"
                f"<span style='font-size:.68rem;color:#9ca3af;margin-left:auto'>"
                f"Net&nbsp;<b style='color:{'#22c55e' if _net>=0 else '#ef4444'}'>"
                f"${_net:+.2f}</b></span>"
                f"</div>",
                unsafe_allow_html=True,
            )
            st.plotly_chart(
                _fig_j, use_container_width=True,
                config={"displayModeBar": False},
            )
            # Close the card border
            st.markdown(
                "<div style='height:1px;background:rgba(255,255,255,0.07);"
                "border-radius:0 0 6px 6px;margin-top:-8px;margin-bottom:8px'></div>",
                unsafe_allow_html=True,
            )

        # ── 4. Open positions ─────────────────────────────────────────────────
        if _journal_open:
            st.markdown(
                f"<div style='font-size:.6rem;font-weight:700;color:{T['muted']};"
                f"text-transform:uppercase;letter-spacing:.08em;margin-bottom:6px;margin-top:4px'>"
                f"Open Positions</div>",
                unsafe_allow_html=True,
            )
            _ocards = '<div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px">'
            for _ot in _journal_open:
                _otp  = str(_ot.get("option_type", "")).upper()
                _otc  = T["accent"] if _otp == "CALL" else T["red"]
                _otbg = "rgba(37,99,235,.06)" if _otp == "CALL" else "rgba(220,38,38,.06)"
                _ocards += (
                    f"<div style='background:{_otbg};border:1px solid {_otc}55;"
                    f"border-radius:8px;padding:8px 14px;flex:1;min-width:140px;max-width:200px'>"
                    f"<div style='font-size:.75rem;font-weight:800;color:{_otc}'>"
                    f"{_ot.get('ticker','')} {_otp}</div>"
                    f"<div style='font-size:.6rem;color:{T['muted']};margin-top:2px'>"
                    f"${_ot.get('strike','')} · {_ot.get('contracts',1)}c</div>"
                    f"<div style='font-size:.55rem;color:{T['muted']};opacity:.7;margin-top:1px;"
                    f"word-break:break-all'>{str(_ot.get('contract_symbol',''))[:22]}</div>"
                    f"</div>"
                )
            _ocards += "</div>"
            st.markdown(_ocards, unsafe_allow_html=True)
            _btn_cols = st.columns(min(len(_journal_open), 6))
            for _ci, _ot in enumerate(_journal_open):
                _otp = str(_ot.get("option_type", "")).upper()
                with _btn_cols[_ci % 6]:
                    if st.button(f"✕ Close {_ot['ticker']} {_otp}",
                                 key=f"j_close_{_ot['id']}", use_container_width=True):
                        try:
                            _res = close_trade_by_id(_ot["id"])
                            if _res.get("ok"):
                                st.success(f"✅ {_res['message']}")
                                st.rerun()
                            else:
                                st.error(f"⚠️ {_res['message']}")
                        except Exception as _jce:
                            st.error(f"Close failed: {_jce}")

        # ── 5. Filters ────────────────────────────────────────────────────────
        st.markdown(
            f"<div style='font-size:.6rem;font-weight:700;color:{T['muted']};"
            f"text-transform:uppercase;letter-spacing:.08em;margin-bottom:4px;margin-top:14px'>"
            f"Filter Trades</div>",
            unsafe_allow_html=True,
        )
        col_f1, col_f2, col_f3 = st.columns(3)
        with col_f1:
            ticker_filter = st.multiselect("Ticker", options=df_j["ticker"].unique().tolist())
        with col_f2:
            result_filter = st.selectbox(
                "Result", ["All", "Open only", "Wins only", "Losses only"]
            )
        with col_f3:
            _reason_opts = (
                df_j["exit_reason_disp"]
                .loc[df_j["exit_reason_disp"] != "—"]
                .dropna().unique().tolist()
            )
            reason_filter = st.multiselect("Exit Reason", options=_reason_opts)

        filtered = df_j.copy()
        if ticker_filter:
            filtered = filtered[filtered["ticker"].isin(ticker_filter)]
        if result_filter == "Open only":
            filtered = filtered[filtered["_is_open"]]
        elif result_filter == "Wins only":
            filtered = filtered[filtered["realized_pnl"] > 0]
        elif result_filter == "Losses only":
            filtered = filtered[filtered["realized_pnl"].notna() & (filtered["realized_pnl"] <= 0)]
        if reason_filter:
            filtered = filtered[filtered["exit_reason_disp"].isin(reason_filter)]

        st.caption(f"Showing {len(filtered)} of {len(df_j)} trades")

        # ── 6. Trade table ────────────────────────────────────────────────────
        display_cols = {
            "result": "Result", "pnl_fmt": "P&L",
            "entry_time": "Entry", "exit_time": "Exit", "ticker": "Ticker",
            "option_type": "Type", "strike": "Strike", "contracts": "Qty",
            "opt_entry": "Opt Entry", "opt_exit": "Opt Exit",
            "signal_short": "Signal", "exit_reason_disp": "Exit Reason",
            "notes": "Notes",
        }
        disp = filtered.copy()
        for _col in ("signal_short", "exit_reason_disp"):
            disp[_col] = disp[_col].map(
                lambda v: f"<div style='max-width:140px;word-break:break-word;"
                          f"white-space:normal;'>{v}</div>"
            )
        _journal_col_widths = [
            "5%", "5%",
            "5%", "5%", "4%", "4%", "4%", "3%",
            "5%", "5%",
            "12%", "12%",
            "31%",
        ]
        st.markdown(NOTE_MODAL_CSS, unsafe_allow_html=True)
        st.markdown(
            _html_table(
                disp[list(display_cols.keys())].rename(columns=display_cols),
                col_widths=_journal_col_widths,
            ),
            unsafe_allow_html=True,
        )

        # ── 7. Summary footer ─────────────────────────────────────────────────
        _f_closed    = filtered[filtered["realized_pnl"].notna()]
        _ff_pnl_val  = _f_closed["realized_pnl"].sum() if len(_f_closed) else None
        _ff_total    = f"${_ff_pnl_val:+.2f}"  if _ff_pnl_val is not None else "—"
        _ff_total_c  = ("#16a34a" if _ff_pnl_val and _ff_pnl_val >= 0
                        else "#dc2626" if _ff_pnl_val is not None else T["muted"])
        _all_pnl_val = _all_closed_j["realized_pnl"].sum() if len(_all_closed_j) else None
        _all_total   = f"${_all_pnl_val:+.2f}" if _all_pnl_val is not None else "—"
        _all_total_c = ("#16a34a" if _all_pnl_val and _all_pnl_val >= 0
                        else "#dc2626" if _all_pnl_val is not None else T["muted"])
        _ff_wr       = (f"{(_f_closed['realized_pnl'] > 0).sum() / len(_f_closed) * 100:.1f}%"
                        if len(_f_closed) else "—")
        _ff_avg      = (f"${_f_closed['realized_pnl'].mean():+.2f}"
                        if len(_f_closed) else "—")
        st.markdown(f"""
<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:0;
            margin-top:18px;border:1px solid {T['border']};border-radius:10px;overflow:hidden">
  <div style="text-align:center;padding:12px 8px">
    <div style="font-size:.56rem;color:{T['muted']};text-transform:uppercase;
                letter-spacing:.07em;font-weight:700;margin-bottom:4px">Filtered P&amp;L</div>
    <div style="font-size:1rem;font-weight:800;font-family:'JetBrains Mono',monospace;
                color:{_ff_total_c}">{_ff_total}</div>
  </div>
  <div style="text-align:center;padding:12px 8px;border-left:1px solid {T['border']}">
    <div style="font-size:.56rem;color:{T['muted']};text-transform:uppercase;
                letter-spacing:.07em;font-weight:700;margin-bottom:4px">All Trades P&amp;L</div>
    <div style="font-size:1rem;font-weight:800;font-family:'JetBrains Mono',monospace;
                color:{_all_total_c}">{_all_total}</div>
  </div>
  <div style="text-align:center;padding:12px 8px;border-left:1px solid {T['border']}">
    <div style="font-size:.56rem;color:{T['muted']};text-transform:uppercase;
                letter-spacing:.07em;font-weight:700;margin-bottom:4px">Win Rate</div>
    <div style="font-size:1rem;font-weight:800;color:{T['text']}">{_ff_wr}</div>
  </div>
  <div style="text-align:center;padding:12px 8px;border-left:1px solid {T['border']}">
    <div style="font-size:.56rem;color:{T['muted']};text-transform:uppercase;
                letter-spacing:.07em;font-weight:700;margin-bottom:4px">Avg / Trade</div>
    <div style="font-size:1rem;font-weight:800;font-family:'JetBrains Mono',monospace;
                color:{T['text']}">{_ff_avg}</div>
  </div>
</div>
<div style="margin-top:6px;font-size:.58rem;color:{T['muted']}">
  💡 <b>Filtered</b> = trades matching the filters. <b>All Trades</b> = full journal.
  Closed trades only.
</div>
""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 6: SESSION AUDIT
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "audit":
    import math as _math
    import sqlite3 as _sqlite3
    from datetime import datetime as _dt, timedelta as _td

    st.markdown("# 🔬  Session Audit")
    st.caption(
        "Runs the full signal replay across all 8 strategies and 5 tickers. "
        "Shows what fired, what was traded, what was missed, and whether "
        "anything in the bot's config is worth adjusting."
    )

    # ── Network gap warning ───────────────────────────────────────────────────
    _bs_audit = _read_bot_state()
    _gap_min  = _bs_audit.get("data_gap_minutes", 0)
    _last_fetch = _bs_audit.get("last_successful_bar_fetch")
    if _gap_min and _gap_min >= 5:
        st.error(
            f"⚠️ **Network gap detected:** the bot was without bar data for "
            f"**{_gap_min} minutes** today (last clean fetch: "
            f"{str(_last_fetch)[11:16] if _last_fetch else 'unknown'} ET). "
            f"Entries made during this window used stale or missing data."
        )

    # ── Date selector + run button ────────────────────────────────────────────
    _audit_col1, _audit_col2, _audit_col3 = st.columns([2, 1, 1])
    with _audit_col1:
        _audit_date = st.date_input(
            "Session date",
            value=_dt.now().date(),
            key="audit_date_picker",
        ).strftime("%Y-%m-%d")
    with _audit_col2:
        st.markdown("<div style='margin-top:28px'></div>", unsafe_allow_html=True)
        _run_audit = st.button("▶  Run Audit", type="primary", key="run_audit_btn")
    with _audit_col3:
        st.markdown("<div style='margin-top:28px'></div>", unsafe_allow_html=True)
        # Auto-trigger after 4pm ET if viewing today and no cached result yet
        _now_et_audit = _dt.now()
        _is_after_close = _now_et_audit.hour >= 16
        _is_today = (_audit_date == _dt.now().strftime("%Y-%m-%d"))
        if _is_today and _is_after_close:
            st.caption("🟢 Auto-available after market close")

    # Checkpoints used throughout the render — defined here so both the
    # computation block and the render block can reference it.
    CHKPTS = [20, 30, 45, 60]

    # Cache key — invalidate if date changes
    _cache_key = f"audit_result_{_audit_date}"
    if _run_audit:
        st.session_state.pop(_cache_key, None)

    if _run_audit or (_is_today and _is_after_close and _cache_key not in st.session_state):
        # ── Run the replay ────────────────────────────────────────────────────
        with st.spinner("Fetching bars and replaying all 8 strategies…"):
            try:
                import risk as _risk_mod
                _orig_kl = _risk_mod.check_kill_lock
                _risk_mod.check_kill_lock = lambda: (False, "")  # replay mode

                from broker import AlpacaClient as _AC
                from signals import bars_to_df as _b2df
                from strategy_router import route_signals as _rs
                from config import TICKER_UNIVERSE as _TU

                _ac_audit = _AC()

                # Pull all trades for the day
                _conn_a = _sqlite3.connect(str(DB_PATH_PAPER))
                _conn_a.row_factory = _sqlite3.Row
                _all_day_trades = [dict(r) for r in _conn_a.execute(
                    "SELECT * FROM trades WHERE entry_time LIKE ? ORDER BY entry_time",
                    [f"{_audit_date}%"]
                ).fetchall()]
                _closed_trades = [t for t in _all_day_trades if t.get("status") == "closed"]
                _conn_a.close()

                # Fetch bars + replay signals
                _bars_map = {}
                _all_sigs = []
                for _tk in _TU:
                    _raw, _err, _ = _ac_audit.get_session_bars(_tk, "1Min")
                    if _err or not _raw:
                        continue
                    _df1m = _b2df(_raw)
                    _df_day = _df1m[_df1m["time"].dt.date.astype(str) == _audit_date].copy()
                    if _df_day.empty:
                        continue
                    _bars_map[_tk] = _df_day.reset_index(drop=True)
                    _h5, _he = _ac_audit.get_bars(_tk, "5Min", limit=1500)
                    if not _he and _h5:
                        _dfh = _b2df(_h5)
                        _dfh = _dfh[_dfh["time"].dt.date.astype(str) < _audit_date]
                        _aug = pd.concat([_dfh, _df_day], ignore_index=True).sort_values("time").reset_index(drop=True)
                    else:
                        _aug = _df_day.copy()
                    for _sig in _rs(_aug, _tk, enabled_strategies=None):
                        _all_sigs.append({
                            "ticker": _tk,
                            "strategy_id": _sig.strategy_id,
                            "direction": _sig.direction,
                            "option_type": "call" if _sig.direction == "bullish" else "put",
                            "confidence": _sig.confidence,
                            "rvol": _sig.rvol,
                            "trigger_bar": pd.to_datetime(_sig.trigger_bar),
                        })
                _all_sigs.sort(key=lambda s: s["trigger_bar"])
                _risk_mod.check_kill_lock = _orig_kl  # restore

                # Match signals to trades
                _matched_ids = set()
                _orb_taken   = set()
                _sig_rows    = []
                for _s in _all_sigs:
                    _match = None
                    for _t in _closed_trades:
                        if (_t["id"] not in _matched_ids
                                and _t["ticker"] == _s["ticker"]
                                and _t["strategy_id"] == _s["strategy_id"]
                                and (_t["option_type"] or "").lower() == _s["option_type"]):
                            _match = _t
                            _matched_ids.add(_t["id"])
                            if _s["strategy_id"] == "INST_ORB":
                                _orb_taken.add(_s["ticker"])
                            break
                    _open_at = [_t for _t in _all_day_trades
                                if pd.to_datetime(_t["entry_time"]) <= _s["trigger_bar"]
                                and (not _t.get("exit_time")
                                     or pd.to_datetime(_t["exit_time"]) > _s["trigger_bar"])]
                    _n_open = len(_open_at)
                    if _match:
                        _delay = (pd.to_datetime(_match["entry_time"]) - _s["trigger_bar"]).total_seconds() / 60
                        _status = ("TAKEN" + (f" (+{_delay:.0f}min late)" if _delay > 5 else ""))
                        _viable = False
                    elif _s["strategy_id"] == "INST_ORB" and _s["ticker"] in _orb_taken:
                        _status = "BLOCKED (ORB already traded)"
                        _viable = False
                    elif _n_open >= 2:
                        _status = f"BLOCKED ({_n_open} positions open)"
                        _viable = False
                    else:
                        _status = "MISSED ← viable"
                        _viable = True
                    _sig_rows.append({**_s, "match": _match, "n_open": _n_open,
                                      "status": _status, "viable": _viable})

                # BS helpers (inline, no import)
                import math as _m2
                def _bsp(S, K, now_dt, exp_dt, is_call, sigma=0.16, r=0.05):
                    try:
                        T = max((exp_dt - now_dt).total_seconds(), 60) / (365*24*3600)
                        d1 = (_m2.log(S/K) + (r + .5*sigma**2)*T) / (sigma*_m2.sqrt(T))
                        d2 = d1 - sigma*_m2.sqrt(T)
                        N  = lambda x: .5*(1+_m2.erf(x/_m2.sqrt(2)))
                        disc = _m2.exp(-r*T)
                        return max(.01, S*N(d1)-K*disc*N(d2) if is_call else K*disc*N(-d2)-S*N(-d1))
                    except Exception:
                        return max(.01, S*.013)

                def _iv(S, K, now_dt, exp_dt, is_call, target, r=0.05):
                    lo, hi = .01, 5.0
                    for _ in range(60):
                        mid = (lo + hi) / 2
                        if _bsp(S, K, now_dt, exp_dt, is_call, mid, r) < target:
                            lo = mid
                        else:
                            hi = mid
                    return (lo + hi) / 2

                def _near(df, ts):
                    e = df[df["time"] <= ts]
                    return None if e.empty else e.iloc[-1]

                # Expiry date (default to nearest Friday)
                _exp_str = "2026-06-29"
                if _closed_trades:
                    _exp_str = _closed_trades[0].get("expiry", _exp_str) or _exp_str
                _exp_dt = _dt.strptime(_exp_str, "%Y-%m-%d").replace(hour=16)

                CHKPTS = [20, 30, 45, 60]

                # Per-ticker avg IV from real trades
                _ticker_ivs: dict = {}
                for _t in _closed_trades:
                    _df = _bars_map.get(_t["ticker"])
                    if _df is None: continue
                    _b0 = _near(_df, pd.to_datetime(_t["entry_time"]))
                    if _b0 is None: continue
                    _ic = (_t["option_type"] or "").lower() == "call"
                    _iv_val = _iv(float(_b0["close"]), float(_t["strike"]),
                                  pd.to_datetime(_t["entry_time"]).to_pydatetime(),
                                  _exp_dt, _ic, float(_t["entry_price"]))
                    _ticker_ivs.setdefault(_t["ticker"], []).append(_iv_val)
                _avg_iv = {tk: sum(v)/len(v) for tk, v in _ticker_ivs.items()}
                _DEFAULT_IV = {"SPY": .15, "QQQ": .18, "AAPL": .25, "NVDA": .40, "TSLA": .50}

                # Compute P&L checkpoints for actual trades
                _actual_rows = []
                _actual_total = 0.0
                _totals_a = {c: 0.0 for c in CHKPTS}
                for _t in _closed_trades:
                    _df = _bars_map.get(_t["ticker"])
                    if _df is None: continue
                    _edt = pd.to_datetime(_t["entry_time"])
                    _b0 = _near(_df, _edt)
                    if _b0 is None: continue
                    _S0 = float(_b0["close"])
                    _ic = (_t["option_type"] or "").lower() == "call"
                    _iv_t = _iv(_S0, float(_t["strike"]), _edt.to_pydatetime(),
                                 _exp_dt, _ic, float(_t["entry_price"]))
                    _pnl_a = float(_t["realized_pnl"])
                    _actual_total += _pnl_a
                    _cp_map = {}
                    for _c in CHKPTS:
                        _bN = _near(_df, _edt + _td(minutes=_c))
                        if _bN is None: continue
                        _SN = float(_bN["close"])
                        _cp = (_bsp(_SN, float(_t["strike"]),
                                    (_edt + _td(minutes=_c)).to_pydatetime(),
                                    _exp_dt, _ic, _iv_t) - float(_t["entry_price"])) * 100
                        _cp_map[_c] = _cp
                        _totals_a[_c] += _cp
                    _actual_rows.append({
                        "id": _t["id"], "ticker": _t["ticker"],
                        "type": (_t["option_type"] or "").upper(),
                        "strategy": _t["strategy_id"],
                        "entry": _edt.strftime("%H:%M"),
                        "exit_reason": (_t.get("exit_reason") or "")[:30],
                        "actual_pnl": _pnl_a,
                        "iv": _iv_t,
                        **{f"+{c}m": _cp_map.get(c) for c in CHKPTS},
                    })

                # Compute P&L for viable missed signals
                _missed_rows = []
                _totals_m = {c: 0.0 for c in CHKPTS}
                for _sr in _sig_rows:
                    if not _sr["viable"]: continue
                    _df = _bars_map.get(_sr["ticker"])
                    if _df is None: continue
                    _trig = _sr["trigger_bar"]
                    _b0 = _near(_df, _trig)
                    if _b0 is None: continue
                    _S0 = float(_b0["close"])
                    _ic = _sr["direction"] == "bullish"
                    _step = 1.0 if _sr["ticker"] in ("SPY", "QQQ") else 2.5
                    _K = round((_math.ceil(_S0/_step)*_step if _ic else _math.floor(_S0/_step)*_step), 2)
                    _iv_m = _avg_iv.get(_sr["ticker"], _DEFAULT_IV.get(_sr["ticker"], .30))
                    _entry_px = _bsp(_S0, _K, _trig.to_pydatetime(), _exp_dt, _ic, _iv_m)
                    _cp_map = {}
                    for _c in CHKPTS:
                        _bN = _near(_df, _trig + _td(minutes=_c))
                        if _bN is None: continue
                        _SN = float(_bN["close"])
                        _cp = (_bsp(_SN, _K, (_trig + _td(minutes=_c)).to_pydatetime(),
                                    _exp_dt, _ic, _iv_m) - _entry_px) * 100
                        _cp_map[_c] = _cp
                        _totals_m[_c] += _cp
                    _missed_rows.append({
                        "ticker": _sr["ticker"], "strategy": _sr["strategy_id"],
                        "direction": _sr["direction"], "trigger": _trig.strftime("%H:%M"),
                        "strike": _K, "type": "CALL" if _ic else "PUT",
                        "iv": _iv_m, "entry_px": _entry_px,
                        **{f"+{c}m": _cp_map.get(c) for c in CHKPTS},
                    })

                st.session_state[_cache_key] = {
                    "sig_rows": _sig_rows,
                    "actual_rows": _actual_rows,
                    "missed_rows": _missed_rows,
                    "actual_total": _actual_total,
                    "totals_a": _totals_a,
                    "totals_m": _totals_m,
                    "n_trades": len(_closed_trades),
                    "n_signals": len(_all_sigs),
                }

            except Exception as _ae:
                st.error(f"Audit failed: {_ae}")
                import traceback
                st.code(traceback.format_exc())

    # ── Render cached results ─────────────────────────────────────────────────
    if _cache_key in st.session_state:
        _R = st.session_state[_cache_key]
        _sig_rows    = _R["sig_rows"]
        _actual_rows = _R["actual_rows"]
        _missed_rows = _R["missed_rows"]
        _actual_total = _R["actual_total"]
        _totals_a    = _R["totals_a"]
        _totals_m    = _R["totals_m"]

        st.markdown(
            f"**{_R['n_signals']} signal(s)** replayed across "
            f"{len(set(s['ticker'] for s in _sig_rows))} ticker(s) · "
            f"**{_R['n_trades']} trade(s)** in DB"
        )

        # ── Signal Timeline ───────────────────────────────────────────────────
        with st.expander("📡  Signal Timeline — Every Strategy Signal Today", expanded=True):
            if not _sig_rows:
                st.info("No signals detected. Check that bars were fetched correctly.")
            for _sr in _sig_rows:
                _icon = "✅" if "TAKEN" in _sr["status"] else ("🚫" if "BLOCKED" in _sr["status"] else "⚠️")
                _col_a, _col_b = st.columns([1, 3])
                with _col_a:
                    st.markdown(
                        f"**{_sr['trigger_bar'].strftime('%H:%M')}** · "
                        f"{_sr['ticker']} {_sr['option_type'].upper()} · "
                        f"{_sr['strategy_id']}"
                    )
                with _col_b:
                    _pnl_str = ""
                    if _sr.get("match"):
                        _pnl_str = f" · P&L **${float(_sr['match'].get('realized_pnl', 0)):+.2f}**"
                    st.markdown(f"{_icon} {_sr['status']}{_pnl_str}")

        # ── Section A: Hold-longer analysis ──────────────────────────────────
        st.markdown("### 📈  Section A — Actual Trades: Hold Longer?")
        st.caption(
            "Modelled P&L if each trade was held to +20/30/45/60 min instead of "
            "the 20-min timebox. Calibrated to your real entry fills."
        )
        if _actual_rows:
            for _ar in _actual_rows:
                with st.expander(
                    f"Trade #{_ar['id']} · {_ar['ticker']} {_ar['type']} · "
                    f"{_ar['strategy']} · entry {_ar['entry']} · "
                    f"P&L ${_ar['actual_pnl']:+.2f}",
                    expanded=False,
                ):
                    st.caption(f"Exit reason: {_ar['exit_reason']}  ·  Implied vol: {_ar['iv']:.0%}")
                    _hl_cols = st.columns(4)
                    for _ci, _c in enumerate(CHKPTS):
                        _v = _ar.get(f"+{_c}m")
                        with _hl_cols[_ci]:
                            _delta = (_v - _ar["actual_pnl"]) if _v is not None else None
                            st.metric(
                                f"+{_c}min",
                                f"${_v:+.2f}" if _v is not None else "—",
                                delta=f"{_delta:+.2f} vs actual" if _delta is not None else None,
                            )

            st.markdown("**Totals if ALL trades held to each checkpoint:**")
            _tot_cols = st.columns(4)
            for _ci, _c in enumerate(CHKPTS):
                with _tot_cols[_ci]:
                    _delta = _totals_a[_c] - _actual_total
                    st.metric(f"+{_c}min", f"${_totals_a[_c]:+.2f}",
                              delta=f"{_delta:+.2f} vs actual")

        # ── Section B: Viable missed signals ─────────────────────────────────
        st.markdown("### 🕵️  Section B — Viable Missed Signals")
        if not _missed_rows:
            st.success("No viable missed signals — every qualified signal was taken or the concurrent-position cap explains all gaps.")
        else:
            st.caption("Hypothetical P&L using ATM strikes, implied vol from today's real fills.")
            for _mr in _missed_rows:
                with st.expander(
                    f"{_mr['trigger']} · {_mr['ticker']} {_mr['type']} ${_mr['strike']:.2f} · "
                    f"{_mr['strategy']} · IV {_mr['iv']:.0%}",
                    expanded=True,
                ):
                    _m_cols = st.columns(4)
                    for _ci, _c in enumerate(CHKPTS):
                        _v = _mr.get(f"+{_c}m")
                        with _m_cols[_ci]:
                            st.metric(f"+{_c}min", f"${_v:+.2f}" if _v is not None else "—")

            st.markdown("**Missed signals sub-total (hypothetical):**")
            _ms_cols = st.columns(4)
            for _ci, _c in enumerate(CHKPTS):
                with _ms_cols[_ci]:
                    st.metric(f"+{_c}min", f"${_totals_m[_c]:+.2f}")

        # ── Grand total ───────────────────────────────────────────────────────
        st.markdown("### 💰  Grand Total")
        _gt_cols = st.columns(5)
        with _gt_cols[0]:
            st.metric("Actual (20-min timebox)", f"${_actual_total:+.2f}")
        for _ci, _c in enumerate(CHKPTS):
            with _gt_cols[_ci + 1]:
                _combo = _totals_a[_c] + _totals_m[_c]
                st.metric(f"Held +{_c}min + missed",
                          f"${_combo:+.2f}",
                          delta=f"{_combo - _actual_total:+.2f}")

        # ── Tuning Recommendations ────────────────────────────────────────────
        st.markdown("---")
        st.markdown("### 🧠  Tuning Recommendations")
        _recs = []

        # 1. Timebox: did holding longer consistently help?
        _better_at_45 = sum(
            1 for _ar in _actual_rows
            if _ar.get("+45m") is not None and _ar["+45m"] > _ar["actual_pnl"]
        )
        _n_actual = len(_actual_rows)
        if _n_actual >= 4 and _better_at_45 >= int(_n_actual * 0.75):
            _recs.append((
                "⏱ Consider extending EARLY_TIMEBOX_MIN",
                f"{_better_at_45}/{_n_actual} trades were more profitable at +45min. "
                f"Holding an extra 25 minutes would have improved outcomes on "
                f"{_better_at_45} of today's {_n_actual} trades. "
                f"Run this audit for 5+ more sessions before changing the timebox — "
                f"one day is not enough data to act on. "
                f"**Current:** `EARLY_TIMEBOX_MIN = 20`  →  **Suggested to test:** `25` or `30`"
            ))
        elif _n_actual >= 4 and _better_at_45 <= int(_n_actual * 0.25):
            _recs.append((
                "⏱ Timebox looks correctly calibrated",
                f"Only {_better_at_45}/{_n_actual} trades improved at +45min. "
                f"The 20-minute cutoff is doing its job of killing theta decay. No change needed."
            ))

        # 2. Strategy diversity: only one strategy fired all day?
        _strats_fired = set(s["strategy_id"] for s in _sig_rows)
        if len(_strats_fired) == 1 and "INST_ORB" in _strats_fired:
            _recs.append((
                "📊 Only INST_ORB fired today — other 7 strategies are quiet",
                "Today's signals were 100% INST_ORB. This is normal in a trending morning, "
                "but if this pattern holds across multiple sessions it may indicate the other "
                "strategy thresholds (BOS_MSS, VWAP_PB, FVG, MID_BRK, AFT_REV, TREND_CONT, "
                "CHAN_BREAK) are too tight for current market conditions. "
                "No action needed yet — track for 1–2 weeks."
            ))

        # 3. Network gap
        if _gap_min and _gap_min >= 5:
            _recs.append((
                "🌐 Network watchdog triggered — reconnect logic is now active",
                f"The bot was offline for {_gap_min}+ minutes today. "
                f"The new watchdog (added today) will log a warning after 5 minutes and "
                f"skip strategy evaluation during gaps so stale data can't drive a bad entry. "
                f"**Action:** If outages keep happening, check your internet stability "
                f"or run the bot on a cloud VM (e.g., an AWS t3.micro in us-east-1 which "
                f"has sub-1ms latency to Alpaca's servers)."
            ))

        # 4. Viable missed signals
        if _missed_rows:
            _best_missed = max((_mr.get("+30m", 0) or 0) for _mr in _missed_rows)
            _recs.append((
                f"🎯 {len(_missed_rows)} viable signal(s) not traded today",
                f"These signals fired with open position slots available but weren't executed. "
                f"Best hypothetical P&L at +30min: ${_best_missed:+.2f}. "
                f"Most common cause is the network outage preventing the bot from acting on "
                f"the early-session ORB window. No strategy change needed — "
                f"fixing the infrastructure (stable connection, reconnect watchdog) "
                f"is the right fix here."
            ))

        # 5. Signal-replay gap (signals fired but can't be matched to DB trades)
        _taken_count  = sum(1 for _sr in _sig_rows if "TAKEN" in _sr["status"])
        _db_trade_count = _R["n_trades"]
        if _db_trade_count > _taken_count and _taken_count > 0:
            _gap_count = _db_trade_count - _taken_count
            _recs.append((
                f"🔍 {_gap_count} DB trade(s) can't be matched to a replayed signal",
                f"The bot made {_db_trade_count} trades today but the offline signal replay "
                f"only reproduces {_taken_count} of them. This means the live bot's signal "
                f"evaluation (using truncated, in-session bar windows) produced different "
                f"RVOL/MSA readings than the end-of-day replay. "
                f"**Not a trading error** — the entries were valid at the time. "
                f"But it does mean this audit tool underestimates what the bot actually saw. "
                f"Worth investigating the RVOL calibration consistency between live and replay."
            ))

        if not _recs:
            st.success("✅ Nothing obvious to tune. Keep running daily and watch for patterns over time.")
        else:
            for _title, _body in _recs:
                st.warning(f"**{_title}**\n\n{_body}")

        st.caption(
            "⚠️ All option P&L figures are modelled (Black-Scholes), not real fills. "
            "Treat as directional estimates. Do not change bot parameters based on a single session."
        )

    else:
        _now_et_chk = _dt.now()
        if _now_et_chk.hour < 16:
            st.info(
                "Click **▶ Run Audit** to replay today's session, or wait until after "
                "4:00 PM ET when it becomes available automatically."
            )
        else:
            st.info("Click **▶ Run Audit** to load today's session audit.")

# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 6: INCOME ROADMAP
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "roadmap":
    st.markdown("# 🗺  Income Roadmap & Projections")
    _rm_settings = get_settings()
    _flip_on     = _rm_settings.get("flip_trading_enabled", True)
    _growth_on   = _rm_settings.get("growth_mode", False)
    st.caption(
        "8-Strategy Blend (ORB · BOS/MSS · VWAP Pullback · FVG · Mid-Day Breakdown · "
        "Afternoon Reversal · Trend Continuation · Channel Rejection) · top-5 scanner · "
        + ("3% risk until $50k → 1% · " if _growth_on else "1% risk · ")
        + ("flip re-entry enabled · " if _flip_on else "")
        + "R:R gate (1.2 → 1.6, balance-based) · 45-min time-box · dynamic stop · 10% daily loss hard cap"
    )

    current_balance = LIVE_STATE.get("account_balance", STARTING_CAPITAL)
    settings        = _rm_settings
    stats           = get_statistics()
    live_wr         = stats.get("win_rate", 0.55)

    if not current_balance:
        st.info("ℹ️ No live balance — projections use your manually entered starting capital.")

    # ── Controls ─────────────────────────────────────────────────────────────────
    ctrl1, ctrl2, ctrl3, ctrl4 = st.columns(4)
    with ctrl1:
        sim_start = st.number_input(
            "Starting Capital ($)",
            min_value=100, max_value=500_000,
            value=max(100, int(current_balance or STARTING_CAPITAL)),
            step=100,
        )
    with ctrl2:
        wr_pct = st.slider(
            "Win Rate %",
            min_value=40, max_value=68,
            value=max(40, min(65, int(live_wr * 100) if live_wr > 0 else 55)),
            step=1,
            help="ORB with RVOL ≥ 200% + VWAP gate typically achieves 50–62%.",
        ) / 100
    with ctrl3:
        monthly_target = st.slider(
            "Income Target ($/mo)",
            min_value=500, max_value=20_000,
            value=int(st.session_state.get("income_goal", 3000)),
            step=500,
        )
    with ctrl4:
        show_growth = st.toggle(
            "Show 3% and 5% risk comparison lines in chart",
            value=_growth_on,
            help="Adds two more curves to the chart below showing how the account "
                 "would grow at a constant 3% or 5% risk per trade, for comparison "
                 "against the 1% conservative curve. This is just for comparison — "
                 "your actual risk tier (shown above in 'Active Risk Tier') always "
                 "follows the real settings on the Settings page, regardless of "
                 "this toggle.",
        )
    st.session_state["income_goal"] = monthly_target

    import random as _random

    # ── Strategy constants ────────────────────────────────────────────────────────
    # Per-trade outcome as a fraction of equity (same structure as risk.py math).
    # WIN:  stage-1 half at +50% (×0.95 slip) + stage-2 holdover ≈ 0.90% at 1% risk
    # LOSS: dynamic stop avg 25% of premium (30%→25%→20%) ≈ 0.83% at 1% risk
    # At 3% risk these scale linearly (×3).
    _WIN_MULT  = 0.90    # win  as % of risk budget (baseline, before per-strategy R:R mult)
    _LOSS_MULT = 0.83    # loss as % of risk budget (avg dynamic stop — same for every strategy,
                         # since stop management in risk.py is universal, not per-strategy)

    # ── 8-Strategy Profiles ───────────────────────────────────────────────────────
    # Derived from each strategy's confidence formula in strategy_router.py
    # (_eval_inst_orb, _eval_bos_mss, _eval_vwap_pullback, _eval_fvg,
    # _eval_midday_breakdown, _eval_afternoon_reversal, _eval_trend_cont,
    # _eval_chan_break). Each strategy differs in:
    #   - conf_avg:    its typical signal confidence (drives win-rate scaling below)
    #   - rr_mult:     its typical reward:risk profile relative to the ORB baseline
    #                  (scales the WIN side of the trade only)
    #   - freq_weight: how often it fires relative to the other 7 (sums to 1.00)
    # The loss side is intentionally NOT scaled per-strategy — the dynamic stop
    # ladder (risk.py) applies the same way regardless of which strategy entered.
    STRATEGY_PROFILES: dict[str, dict] = {
        "INST_ORB":   {"name": "Opening Range Breakout", "conf_avg": 0.89, "rr_mult": 1.30, "freq_weight": 0.16},
        "BOS_MSS":    {"name": "Break of Structure",     "conf_avg": 0.79, "rr_mult": 1.15, "freq_weight": 0.10},
        "VWAP_PB":    {"name": "VWAP Pullback",          "conf_avg": 0.71, "rr_mult": 1.05, "freq_weight": 0.16},
        "FVG":        {"name": "Fair Value Gap",         "conf_avg": 0.68, "rr_mult": 1.00, "freq_weight": 0.10},
        "MID_BRK":    {"name": "Mid-Day Breakdown",      "conf_avg": 0.76, "rr_mult": 1.10, "freq_weight": 0.12},
        "AFT_REV":    {"name": "Afternoon Reversal",     "conf_avg": 0.73, "rr_mult": 1.08, "freq_weight": 0.10},
        "TREND_CONT": {"name": "Trend Continuation",     "conf_avg": 0.74, "rr_mult": 1.08, "freq_weight": 0.14},
        "CHAN_BREAK": {"name": "Channel Rejection",      "conf_avg": 0.83, "rr_mult": 1.20, "freq_weight": 0.12},
    }
    # ORB is the strategy the win-rate slider has historically been calibrated
    # against, so it's the reference point for scaling the other 7.
    _REF_CONF      = STRATEGY_PROFILES["INST_ORB"]["conf_avg"]
    _STRAT_IDS     = list(STRATEGY_PROFILES.keys())
    _STRAT_WEIGHTS = [STRATEGY_PROFILES[s]["freq_weight"] for s in _STRAT_IDS]

    def _strategy_win_rate(base_wr: float, strat_id: str) -> float:
        """Scale the slider win-rate per strategy by its confidence vs the ORB baseline."""
        mult = STRATEGY_PROFILES[strat_id]["conf_avg"] / _REF_CONF
        return min(0.70, max(0.40, base_wr * mult))

    def _orb_pcts(risk_pct: float, strat_id: str = "INST_ORB") -> tuple[float, float]:
        """Return (win_pct, loss_pct) fractions of equity for a given risk tier + strategy."""
        rr = STRATEGY_PROFILES[strat_id]["rr_mult"]
        return risk_pct * _WIN_MULT * rr, risk_pct * _LOSS_MULT

    def _blended_ev_frac(risk_pct: float, base_wr: float) -> float:
        """Frequency-weighted EV (as a fraction of equity) blended across all 8 strategies."""
        total = 0.0
        for sid, prof in STRATEGY_PROFILES.items():
            win_pct, loss_pct = _orb_pcts(risk_pct, sid)
            strat_wr = _strategy_win_rate(base_wr, sid)
            total += prof["freq_weight"] * (strat_wr * win_pct - (1 - strat_wr) * loss_pct)
        return total

    # Every trading day now produces at least one trade — with 8 strategies,
    # unlimited re-entry, and 45-min time-box cycling, "no qualifying setup
    # today" essentially never happens in practice. CHOPPY_PROB still rolls
    # per month to dampen the effective win rate on choppy months (see
    # eff_wr below), it just no longer gates whether trades happen at all.
    CHOPPY_PROB          = 0.28
    FLIP_HARD_STOP_RATE  = 0.55
    FLIP_SIGNAL_RATE     = 0.65
    GROWTH_BOUNDARY      = float(settings.get("growth_risk_boundary", 50_000))

    # ── Live risk tier — what the bot is ACTUALLY risking per trade right now ──
    # config.get_risk_tier() is the SAME function risk.py calls fresh before
    # every trade (mirrors the Settings page's "Current Active Settings" panel).
    # It checks the manual risk_per_trade override FIRST — if set to
    # 0.01 / 0.03 / 0.05 it wins outright, ignoring balance and Growth Mode
    # entirely — then falls back to the 4-tier automatic ladder (5%/3%/2%/1%).
    # This — not _growth_on alone — drives every "what's happening with my
    # money right now" display below (Active Risk Tier, EV/Trade, Gross/Month,
    # disclaimer).
    from config import (
        get_risk_tier as _get_rt,
        _VALID_RISK_OVERRIDES as _VRO,
        BOOTSTRAP_RISK_PCT as _BOOT_PCT,
        GROWTH_MODE_RISK_PCT as _GROW_PCT,
        MID_TIER_RISK_PCT as _MID_PCT,
        CONSERVATIVE_RISK_PCT as _CONS_PCT,
        GROWTH_RISK_BOUNDARY_BOOT as _GRB_BOOT_DEFAULT,
        GROWTH_RISK_BOUNDARY_LOW as _GRB_LOW_DEFAULT,
    )
    _live_risk_pct   = _get_rt(current_balance)
    _rpt_raw         = settings.get("risk_per_trade")
    _override_active = _rpt_raw is not None and float(_rpt_raw) in _VRO
    _BOUNDARY_BOOT   = float(settings.get("growth_risk_boundary_boot", _GRB_BOOT_DEFAULT))
    _BOUNDARY_LOW    = float(settings.get("growth_risk_boundary_low",  _GRB_LOW_DEFAULT))

    def _tier_for_balance(bal: float, growth_mode: bool) -> float:
        """
        Risk % this balance gets under the AUTOMATIC 4-tier ladder
        (5% / 3% / 2% / 1%) for a given growth_mode flag, ignoring any manual
        risk_per_trade override. Used by run_orb_sim() to simulate the full
        ladder for the Growth Mode comparison curve.
        """
        if not growth_mode:
            return _CONS_PCT
        if bal < _BOUNDARY_BOOT:
            return _BOOT_PCT
        elif bal < _BOUNDARY_LOW:
            return _GROW_PCT
        elif bal < GROWTH_BOUNDARY:
            return _MID_PCT
        else:
            return _CONS_PCT

    def run_orb_sim(
        start_bal:      float,
        wr:             float,
        seed:           int   = 42,
        months:         int   = 60,
        flip_enabled:   bool  = False,
        growth_mode:    bool  = False,
        fixed_risk_pct: float | None = None,
    ) -> list[dict]:
        """
        Simulate the 8-strategy blend with optional growth mode (full 4-tier
        ladder: 5% under $5k -> 3% $5k-$25k -> 2% $25k-$50k -> 1% at $50k+)
        and flip trading. Each trade randomly draws one of the 8 strategies
        weighted by its real-world firing frequency (freq_weight), then applies
        that strategy's own win-rate scaling (conf_avg vs ORB baseline) and
        reward multiplier (rr_mult) to the outcome.

        If fixed_risk_pct is given, EVERY trade uses that constant risk %
        (e.g. 0.01 / 0.03 / 0.05) instead of the balance-based ladder — this is
        what drives the "1% vs 3% vs 5%" comparison curves on the Growth
        Curves chart. growth_mode/_tier_for_balance is only used when
        fixed_risk_pct is None.
        """
        rng = _random.Random(seed)
        bal = start_bal
        result = []

        for month in range(1, months + 1):
            choppy   = rng.random() < CHOPPY_PROB
            mo_pnl, mo_trades, start_mo = 0.0, 0, bal

            for _day in range(21):
                if bal < 100:
                    break

                # With 8 strategies, flip re-entry, AND 45-min time-box exits
                # that let the bot re-enter the SAME setup repeatedly while a
                # strong trend persists, EVERY trading day now produces a
                # cluster of 1-5 trades — e.g. 5 IWM ORB re-entries cycled via
                # time-box on 2026-06-12. Model: 8% chance of 1 trade, 18%
                # chance of 2, 28% chance of 3, 28% chance of 4, 18% chance of
                # 5 (mean 3.30/day -> ~80 trades/mo with flip on).
                _day_roll = rng.random()
                _day_trades = (5 if _day_roll > 0.82 else
                               4 if _day_roll > 0.54 else
                               3 if _day_roll > 0.26 else
                               2 if _day_roll > 0.08 else 1)

                for _t in range(_day_trades):
                    if bal < 100:
                        break
                    # Pick which of the 8 strategies fired this trade, weighted
                    # by how often each one actually fires (freq_weight).
                    strat_id = rng.choices(_STRAT_IDS, weights=_STRAT_WEIGHTS, k=1)[0]
                    strat_wr = _strategy_win_rate(wr, strat_id)
                    eff_wr   = max(0.40, strat_wr * (0.87 if choppy else 1.0))

                    # Determine risk tier for THIS trade — fixed_risk_pct (if
                    # given) overrides the balance-based ladder entirely.
                    r_pct = (fixed_risk_pct if fixed_risk_pct is not None
                             else _tier_for_balance(bal, growth_mode))
                    orb_win, orb_loss = _orb_pcts(r_pct, strat_id)

                    # ── Normal trade ──────────────────────────────────────
                    won = rng.random() < eff_wr
                    pnl = bal * orb_win if won else -(bal * orb_loss)
                    bal = max(0, bal + pnl)
                    mo_pnl    += pnl
                    mo_trades += 1

                    # ── Flip trade (hard stop only, same strategy re-fires) ─
                    if flip_enabled and not won:
                        flip_extra = (1 - eff_wr) * FLIP_HARD_STOP_RATE * FLIP_SIGNAL_RATE
                        r2     = (fixed_risk_pct if fixed_risk_pct is not None
                                  else _tier_for_balance(bal, growth_mode))
                        w2, l2 = _orb_pcts(r2, strat_id)
                        if rng.random() < flip_extra / max(1 - eff_wr, 0.01):
                            flip_won = rng.random() < max(0.40, eff_wr * 0.92)
                            flip_pnl = bal * w2 if flip_won else -(bal * l2)
                            bal      = max(0, bal + flip_pnl)
                            mo_pnl    += flip_pnl
                            mo_trades += 1

            result.append({
                "month":     month,
                "balance":   round(bal, 2),
                "pnl":       round(mo_pnl, 2),
                "trades":    mo_trades,
                "choppy":    choppy,
                "pct_chg":   round((bal - start_mo) / max(start_mo, 1) * 100, 2),
                "risk_tier": f"{(fixed_risk_pct if fixed_risk_pct is not None else _tier_for_balance(bal, growth_mode))*100:.0f}%",
            })
        return result

    # ── EV math — blended across all 8 strategies (1% risk, flip if enabled) ────
    # Average trades per DAY: run_orb_sim (see the per-day loop above) now
    # gives every trading day an 8% chance of 1 trade, 18% chance of 2, 28%
    # chance of 3, 28% chance of 4, and 18% chance of 5 — expected value
    # 0.08*1 + 0.18*2 + 0.28*3 + 0.28*4 + 0.18*5 = 3.30/day. Over 21 trading
    # days/month that's ~69.3 base trades; flip re-entries (hard-stop losers
    # re-firing the same strategy at a lower effective win rate) add roughly
    # another 16%, bringing the total to ~80/mo with flip enabled. This
    # reflects 45-min time-box re-entries letting the bot cycle the SAME
    # setup multiple times on a strong-trend day (e.g. 5 IWM ORB trades on
    # 2026-06-12), on EVERY trading day rather than just "signal days".
    _DAY_TRADES_MULT    = 0.08 * 1 + 0.18 * 2 + 0.28 * 3 + 0.28 * 4 + 0.18 * 5   # = 3.30
    _flip_extra_per_day = (1 - wr_pct) * FLIP_HARD_STOP_RATE * FLIP_SIGNAL_RATE if _flip_on else 0.0
    _base_trades_month  = 21 * _DAY_TRADES_MULT
    _flip_add_trades    = 21 * _DAY_TRADES_MULT * _flip_extra_per_day
    avg_trades_month = _base_trades_month + _flip_add_trades

    # ev_frac_c = frequency-weighted EV across all 8 strategies at the
    # conservative 1% tier — used only as the basis for the chart's
    # "income target" reference line (required_bal). Live displays (EV/Trade,
    # Gross/Month) use _ev_frac_live, computed later from _live_risk_pct.
    ev_frac_c               = _blended_ev_frac(0.01, wr_pct)
    monthly_return_frac     = ev_frac_c * avg_trades_month
    required_bal            = (monthly_target / monthly_return_frac
                               if monthly_return_frac > 0 else 999_999_999)
    tax_pct                 = float(settings.get("tax_reserve_pct", 25)) / 100
    net_mult                = 1.0 - tax_pct

    # Blended break-even win rate: frequency-weighted average win/loss payout
    # at the 1% tier, independent of the assumed win rate (payout-ratio only).
    _avg_win_c    = sum(p["freq_weight"] * _orb_pcts(0.01, s)[0] for s, p in STRATEGY_PROFILES.items())
    _avg_loss_c   = _LOSS_MULT * 0.01
    break_even_wr = _avg_loss_c / (_avg_win_c + _avg_loss_c)

    # ── Run simulations ───────────────────────────────────────────────────────────
    # Three constant-risk curves (1% / 3% / 5%) — NOT the balance-based ladder —
    # so the chart shows a clean apples-to-apples comparison of "what if every
    # trade risked X%", regardless of account size.
    _sim_1pct = run_orb_sim(
        sim_start, wr_pct, seed=42, months=60,
        flip_enabled=_flip_on, fixed_risk_pct=0.01,
    )
    _sim_3pct = run_orb_sim(
        sim_start, wr_pct, seed=42, months=60,
        flip_enabled=_flip_on, fixed_risk_pct=0.03,
    ) if show_growth else []
    _sim_5pct = run_orb_sim(
        sim_start, wr_pct, seed=42, months=60,
        flip_enabled=_flip_on, fixed_risk_pct=0.05,
    ) if show_growth else []

    # ── Strategy Math Row ─────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### Strategy Math — At Current Balance (8-Strategy Blend)")
    # EV/Trade and Gross/Month below use _live_risk_pct (config.get_risk_tier()),
    # so they always match whatever the bot is actually risking right now —
    # 5% / 3% / 2% / 1% automatic tier, or the manual override if one is set.
    _ev_frac_live = _blended_ev_frac(_live_risk_pct, wr_pct)

    mc1, mc2, mc3, mc4, mc5 = st.columns(5)
    with mc1:
        _rt = f"{_live_risk_pct*100:.0f}%"
        if _override_active:
            st.metric("Active Risk Tier", _rt,
                      help="Manual override (set on the Settings page) — this fixed "
                           "% is used on every trade regardless of balance or Growth "
                           "Mode, until changed or cleared.")
        else:
            st.metric("Active Risk Tier", _rt,
                      help=f"Automatic tier for your current balance "
                           f"(${current_balance:,.0f}) under the Growth Mode ladder: "
                           f"{_BOOT_PCT*100:.0f}% under ${_BOUNDARY_BOOT:,.0f} -> "
                           f"{_GROW_PCT*100:.0f}% up to ${_BOUNDARY_LOW:,.0f} -> "
                           f"{_MID_PCT*100:.0f}% up to ${GROWTH_BOUNDARY:,.0f} -> "
                           f"{_CONS_PCT*100:.0f}% above that.")
    with mc2:
        st.metric("EV / Trade", f"${current_balance * _ev_frac_live:,.2f}",
                  help="Expected dollar gain per trade at current balance and risk tier.")
    with mc3:
        _trd_help = (f"~{_base_trades_month:.1f} base + ~{_flip_add_trades:.1f} flip = ~{avg_trades_month:.1f} total"
                     if _flip_on and _flip_add_trades > 0.05
                     else f"~{avg_trades_month:.1f}/mo (top-5 scanner)")
        st.metric("Avg Trades / Mo", f"{avg_trades_month:.1f}", help=_trd_help)
    with mc4:
        _disp_gross = max(0, current_balance * _ev_frac_live * avg_trades_month)
        _disp_net   = _disp_gross * net_mult
        st.metric("Gross / Month", f"${_disp_gross:,.0f}",
                  delta=f"Net ${_disp_net:,.0f} after {int(tax_pct*100)}% tax")
    with mc5:
        st.metric("Break-even WR", f"{break_even_wr*100:.1f}%",
                  help="Win rate needed to break even. Losing below this shrinks the account.")

    # ── Strategy Mix Breakdown (plain language) ────────────────────────────────────
    # Replaces the old 7-column technical table (confidence-scaled win rates, R:R
    # multipliers, per-strategy EV) with a short, plain-English summary: what each
    # strategy is looking for, and roughly how often it's the one that fires.
    # The underlying math (win rate / R:R / EV) is unchanged — it's still used in
    # the simulation above — it's just no longer dumped on screen as raw numbers.
    _STRATEGY_PLAIN: dict[str, str] = {
        "INST_ORB":   "Catches the first strong move right after the market opens. "
                      "Usually the bot's best-performing setup.",
        "BOS_MSS":    "Jumps in when price breaks through a key level with a rush "
                      "of buying or selling behind it.",
        "VWAP_PB":    "Waits for price to dip back to its average price for the "
                      "day, then bounce.",
        "CHAN_BREAK": "Bets on a bounce when price hits the edge of a recent "
                      "trading range and reverses hard.",
        "TREND_CONT": "Rides the day's overall direction after a brief pause.",
        "MID_BRK":    "Catches a real move during the usually-quiet midday hours.",
        "AFT_REV":    "Looks for a late-day turnaround as traders reposition "
                      "before the close.",
        "FVG":        "Looks for price to fill back into a gap it left behind "
                      "earlier in the day.",
    }
    st.markdown("---")
    st.markdown("#### Strategy Mix — How the 8 Strategies Blend Together")
    st.caption(
        "The bot doesn't rely on one trick — it watches for 8 different setups "
        "all day and only takes the ones that meet its rules. Listed from most "
        "to least common."
    )
    _mix_rows = []
    for _sid, _prof in sorted(
        STRATEGY_PROFILES.items(), key=lambda kv: kv[1]["freq_weight"], reverse=True
    ):
        _mix_rows.append({
            "Strategy":     _prof["name"],
            "How Often":    f"~{_prof['freq_weight']*100:.0f}% of trades",
            "What It Does": _STRATEGY_PLAIN.get(_sid, "Looks for a setup matching this strategy's rules."),
        })
    st.markdown(_html_table(_mix_rows), unsafe_allow_html=True)

    # ── Dual-track Growth Chart ───────────────────────────────────────────────────
    st.markdown("---")
    _chart_title = "Growth Curves"
    if show_growth:
        _chart_title += " — 1% vs 3% vs 5% Risk Per Trade"
    else:
        _chart_title += f" — Conservative 1% Risk · Starting ${sim_start:,.0f}"

    st.markdown(f"#### {_chart_title}")
    _meta_note = (
        f"~{avg_trades_month:.1f} trades/mo · {wr_pct*100:.0f}% win rate (8-strategy blend) · "
        f"{'flip ON · ' if _flip_on else ''}"
        f"Avg Win ≈+{_avg_win_c*100:.2f}% equity · Avg Loss ≈−{_avg_loss_c*100:.2f}% equity (1% tier)"
    )
    st.markdown(
        f"<p style='font-size:0.75rem;color:#000000;margin:0 0 10px 0'>{_meta_note}</p>",
        unsafe_allow_html=True,
    )

    df_1 = pd.DataFrame(_sim_1pct)
    fig_cmp = go.Figure()
    fig_cmp.add_trace(go.Scatter(
        x=df_1["month"], y=df_1["balance"],
        mode="lines", name="1% Risk",
        line=dict(color="#00e5ff", width=2.5),
        hovertemplate="Month %{x}<br>$%{y:,.0f}<extra>1% Risk</extra>",
    ))
    if show_growth and _sim_3pct and _sim_5pct:
        df_3 = pd.DataFrame(_sim_3pct)
        fig_cmp.add_trace(go.Scatter(
            x=df_3["month"], y=df_3["balance"],
            mode="lines", name="3% Risk",
            line=dict(color="#ff9800", width=2.5),
            hovertemplate="Month %{x}<br>$%{y:,.0f}<extra>3% Risk</extra>",
        ))
        df_5 = pd.DataFrame(_sim_5pct)
        fig_cmp.add_trace(go.Scatter(
            x=df_5["month"], y=df_5["balance"],
            mode="lines", name="5% Risk",
            line=dict(color="#ff5252", width=2.5),
            hovertemplate="Month %{x}<br>$%{y:,.0f}<extra>5% Risk</extra>",
        ))

    # Reference line: $100k income-mode marker. (The old "income target"
    # hline was removed — required_bal is often far outside the visible
    # balance range, so it rendered nothing useful. The Income Target
    # control now ties into the "% of Target" column in the table below
    # instead — see that section.)
    fig_cmp.add_hline(y=100_000, line_color="rgba(0,200,240,0.6)", line_width=1,
                      line_dash="dot", annotation_text="$100k — income mode begins",
                      annotation_font_color="rgba(0,200,240,0.6)",
                      annotation_position="right")
    fig_cmp.update_layout(
        template="plotly_white",
        paper_bgcolor=T["plot_paper"], plot_bgcolor=T["plot_bg"],
        height=440, margin=dict(l=10, r=180, t=20, b=40),
        font=dict(color="#000000"),
        # Start zoomed in on the first 12 months; the range slider below the
        # x-axis lets the user drag/expand to see the full 60-month curve.
        xaxis=dict(title="Month", tickmode="linear", dtick=6,
                   range=[0.5, 12.5],
                   rangeslider=dict(visible=True, thickness=0.07),
                   tickfont=dict(color="#000000"), title_font=dict(color="#000000")),
        # Log scale on the Y axis: balances span ~$5k early on up to
        # $100k-$1M+ by month 60, so a linear axis squishes the early
        # (small-dollar) months into an unreadable sliver near zero. Log
        # scale gives every order of magnitude equal visual space.
        # dtick="D2" labels ticks at 1/2/5 of each decade — e.g. $1,000 /
        # $2,000 / $5,000 / $10,000 / $20,000 / $50,000 / $100,000 — so
        # the $5,000-$10,000 range is clearly labeled, not just $0 and $100k.
        yaxis=dict(title="Account Balance", tickprefix="$", tickformat=",.0f",
                   type="log", dtick="D2",
                   tickfont=dict(color="#000000"), title_font=dict(color="#000000")),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0,
                    font=dict(color="#000000")),
        hovermode="x unified",
    )
    st.plotly_chart(fig_cmp, use_container_width=True)

    # Milestone Timeline removed — replaced by strategy playbook below.

    # ── Income Potential Table ────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### Income Potential by Account Size")

    # Tie the "Income Target ($/mo)" control (top of page) into this table:
    # required_bal is the balance needed to hit that target at the 1%
    # conservative tier, and each row's "% of Target" shows how close that
    # account size gets using ITS OWN ladder tier (smaller accounts risk a
    # higher % per trade, so they can approach the target with less capital
    # than the 1%-tier required_bal figure alone implies).
    if required_bal < 10_000_000:
        st.info(
            f"🎯 **Income Target: ${monthly_target:,.0f}/mo** — needs roughly "
            f"**${required_bal:,.0f}** at the 1% conservative tier. The "
            f"\"% of Target\" column below shows how each account size compares, "
            f"using its own tier on the Growth Mode ladder."
        )
    else:
        st.info(
            f"🎯 **Income Target: ${monthly_target:,.0f}/mo** isn't reachable at "
            f"any realistic balance under the 1% tier with the current win rate "
            f"and trade frequency — try lowering the target."
        )

    _override_note = (
        f" Your risk per trade is currently manually fixed at {_live_risk_pct*100:.0f}% "
        f"on the Settings page, which overrides this ladder for your account today."
        if _override_active else ""
    )
    st.caption(
        "Shows how income scales as your account grows under the Growth Mode "
        f"risk ladder ({_BOOT_PCT*100:.0f}% under ${_BOUNDARY_BOOT:,.0f} → "
        f"{_GROW_PCT*100:.0f}% → {_MID_PCT*100:.0f}% → {_CONS_PCT*100:.0f}% at "
        f"${GROWTH_BOUNDARY:,.0f}+), using your {wr_pct*100:.0f}% win rate and "
        f"~{avg_trades_month:.1f} trades/mo." + _override_note
    )
    tier_rows = []
    # $2,500 is included so the table can show the 5% bootstrap tier (sub-$5k) —
    # the smallest/most aggressive rung of the real 4-tier ladder, and the one
    # closest to this account's current balance.
    for _bal in [2_500, 5_000, 10_000, 25_000, 50_000, 100_000, 250_000]:
        # Always use the automatic 4-tier ladder (5%/3%/2%/1%) here, regardless
        # of any manual override — this table's whole point is to show how risk
        # AND income are designed to scale down as the account grows. A manual
        # override (see caption above) applies a single fixed % to every
        # balance instead, which would flatten every row to the same % return
        # and defeat the purpose of a "by account size" table.
        _tier   = _tier_for_balance(_bal, True)
        _ev_day = _blended_ev_frac(_tier, wr_pct)
        _gross  = max(0, _bal * _ev_day * avg_trades_month)
        _net    = _gross * net_mult
        _you    = " ← you" if abs(_bal - sim_start) / max(sim_start, 1) < 0.3 else ""
        _tier_lbl = f"{_tier*100:.0f}%"
        _action = (f"{_tier*100:.0f}% risk · withdraw to target" if _tier == _CONS_PCT
                   else f"{_tier*100:.0f}% risk → compound toward next tier")
        tier_rows.append({
            "Account":                            f"${_bal:,.0f}{_you}",
            "Risk Tier":                          _tier_lbl,
            "Trades/Mo":                          f"{avg_trades_month:.1f}",
            "Gross/Mo":                           f"${_gross:,.0f}",
            f"Net/Mo ({int(tax_pct*100)}% tax)":  f"${_net:,.0f}",
            "Annual Gross":                       f"${_gross*12:,.0f}",
            "% of Target":                        f"{_gross/monthly_target*100:.0f}%",
            "Action":                             _action,
        })
    st.markdown(_html_table(tier_rows), unsafe_allow_html=True)

    # ── Should You Take Profit? ──────────────────────────────────────────────────
    # Load tax profile + ledger here so profit_advisor() has the data it needs
    balance      = current_balance
    profile      = load_tax_profile()
    ledger       = load_sweep_ledger()
    tax_info     = compute_marginal_rate(
        profile.get("salary", 0), profile.get("filing_status", "single"),
        profile.get("state", "TX"), ytd_trading_pnl=profile.get("ytd_trading_pnl", 0.0),
    )
    st.markdown("---")
    st.markdown("### Should You Take Profit?")
    all_trades = get_all_trades(limit=500)
    monthly_pnl = 0.0
    if all_trades:
        cutoff = (datetime.utcnow() - timedelta(days=30)).isoformat()
        monthly_trades = [t for t in all_trades
                         if t.get("exit_time", "") >= cutoff and t.get("realized_pnl")]
        monthly_pnl = sum(t["realized_pnl"] for t in monthly_trades)
    live_trades   = stats.get("total_trades", 0)
    live_win_rate = stats.get("win_rate", 0.0)
    profitable_months = 0
    if all_trades:
        from collections import defaultdict
        mo_map = defaultdict(float)
        for t in all_trades:
            if t.get("exit_time") and t.get("realized_pnl"):
                mo_map[t["exit_time"][:7]] += t["realized_pnl"]
        for pnl in reversed(sorted(mo_map.items(), key=lambda x: x[0])):
            if pnl[1] > 0:
                profitable_months += 1
            else:
                break
    try:
        with get_conn() as conn:
            halt_count = conn.execute(
                "SELECT COUNT(*) FROM system_events WHERE level='WARNING' "
                "AND message LIKE '%DAILY LOSS LIMIT%' "
                "AND ts >= datetime('now','-30 days')"
            ).fetchone()[0]
    except Exception:
        halt_count = 0
    advice = profit_advisor(
        current_balance    = balance,
        starting_capital   = STARTING_CAPITAL,
        total_realized_pnl = stats.get("total_pnl", 0.0),
        monthly_pnl        = monthly_pnl,
        tax_rate_pct       = tax_info["combined_pct"],
        live_trades        = live_trades,
        live_win_rate      = live_win_rate,
        profitable_months  = profitable_months,
        halt_events_30d    = halt_count,
        total_swept_ytd    = ledger.get("total_swept", 0.0),
    )
    rec_colors = {"green": T["green"], "yellow": T["yellow"], "red": T["red"]}
    rec_color  = rec_colors.get(advice["color"], T["accent"])
    st.markdown(f"""
    <div class="trade-card" style="border-left: 4px solid {rec_color}; padding: 1.5rem;">
      <div style="font-size:0.65rem;color:{rec_color};text-transform:uppercase;
                  letter-spacing:0.12em;margin-bottom:8px">Phase {advice['phase']} Recommendation</div>
      <div style="font-family:'Syne',sans-serif;font-size:1.8rem;font-weight:800;
                  color:{rec_color};letter-spacing:-0.02em;margin-bottom:10px">
        {advice['recommendation']}
      </div>
      <div style="font-size:0.72rem;line-height:1.7;max-width:700px">{advice['reason']}</div>
    </div>
    """, unsafe_allow_html=True)
    a1, a2, a3, a4 = st.columns(4)
    with a1:
        st.metric("Current Balance", f"${balance:,.2f}")
    with a2:
        st.metric("Net Monthly (est.)", f"${advice['net_monthly']:,.2f}")
    with a3:
        st.metric("Max Safe Withdrawal",
                  f"${advice['max_withdrawal']:,.2f}" if advice["gates_passed"] else "LOCKED")
    with a4:
        gates_ok = sum(1 for g in advice["safety"]["gates"] if g["passed"])
        total_gates = len(advice["safety"]["gates"])
        st.metric("Safety Gates", f"{gates_ok} / {total_gates}",
                  delta="All clear" if advice["gates_passed"] else f"{total_gates - gates_ok} blocking",
                  delta_color="normal" if advice["gates_passed"] else "inverse")
    st.markdown("---")
    st.markdown("#### 🔒 Withdrawal Safety Gates")
    for gate in advice["safety"]["gates"]:
        icon  = "✅" if gate["passed"] else "🔴"
        with st.expander(f"{icon}  {gate['name']}  —  {gate['actual']}", expanded=not gate["passed"]):
            col_req, col_why = st.columns([1, 2])
            with col_req:
                st.markdown(f"**Required:** {gate['required']}")
                st.markdown(f"**Your value:** {gate['actual']}")
                st.markdown(f"**Status:** {'✅ Passed' if gate['passed'] else '🔴 Blocked'}")
            with col_why:
                st.markdown("**Why this gate exists:**")
                st.markdown(gate["why"])
    if not advice["gates_passed"] and advice.get("cost_of_early_withdrawal"):
        st.error(
            f"💸 **Cost of withdrawing $1,000 today:** "
            f"~${advice['cost_of_early_withdrawal']:,.0f} in foregone future value. "
            f"Patience is the strategy."
        )
    st.caption(
        "⚠️ These are guidelines based on mathematical projections, not licensed financial advice."
    )



# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 7: STRATEGY PLAYBOOKS
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "playbooks":
    st.markdown("# 📐  Strategy Playbooks")
    st.caption(
        "Every strategy the bot runs — trigger conditions, volume gates, time windows, and what to look for on the chart. "
        "Each entry requires RVOL above its gate, no open position, and the active R:R gate "
        "(1.2 small account / 1.6 professional, balance-based — see Settings) after slippage."
    )



    # ── Per-scenario P&L math (balance-aware) ────────────────────────────────
    # FIX 2026-06-20: this previously assumed "$0.50 premium = $50/contract"
    # risk — that's the cost of the WHOLE contract, not what the bot actually
    # risks on it. The bot's real position sizing (risk.py RiskManager.
    # calculate_contracts) only risks ORB_STOP_PCT (20%) of the premium per
    # contract, because the hard stop exits at -20%, not -100%. Using the
    # wrong number here was telling the user they could afford 5x FEWER
    # contracts than the bot's real math allows — corrected to mirror the
    # actual production formula exactly (see risk.py calculate_contracts /
    # max_affordable_premium docstrings — note even THOSE docstrings still
    # say "30%" in their text; the live attribute is 20%, verified directly).
    from config import get_risk_tier as _pb_get_tier, get_settings as _pb_settings
    _PB_ASSUMED_PREMIUM = 0.50      # illustrative — real premium varies by ticker/strike/day
    _PB_STOP_PCT        = 0.20      # risk.py RiskManager.ORB_STOP_PCT (live value, not docstring)
    _PB_STAGE1_GAIN     = 0.50      # risk.py RiskManager.ORB_STAGE1_GAIN
    _PB_STAGE2_TRAIL    = 0.15      # config.py STAGE2_TRAIL_PCT
    _PB_SLIPPAGE        = 0.05      # risk.py RiskManager.SLIPPAGE_PCT

    _pb_bal      = float(_pb_settings().get("last_known_balance", 5_000.0) or 5_000.0)
    _pb_risk_pct = _pb_get_tier(_pb_bal)
    _pb_risk_usd = _pb_bal * _pb_risk_pct
    _pb_risk_per_contract = _PB_ASSUMED_PREMIUM * _PB_STOP_PCT * 100   # real formula
    _pb_contracts  = max(1, int(_pb_risk_usd // _pb_risk_per_contract))
    _pb_position_cost = _pb_contracts * _PB_ASSUMED_PREMIUM * 100      # total $ spent on contracts
    _pb_max_loss   = _pb_contracts * _pb_risk_per_contract             # actual $ lost if stopped out
    _pb_s1_profit  = (_pb_contracts / 2) * (_PB_ASSUMED_PREMIUM * _PB_STAGE1_GAIN) * 100
    _pb_tier_name = (
        "Tier 4 — Bootstrap 5%" if _pb_risk_pct >= 0.05 else
        "Tier 3 — Growth 3%"    if _pb_risk_pct >= 0.03 else
        "Tier 2 — Moderate 2%"  if _pb_risk_pct >= 0.02 else
        "Tier 1 — Conservative 1%"
    )
    st.markdown(
        f"<div style='background:rgba(0,180,80,0.08);border:1px solid rgba(0,150,70,0.35);"
        f"border-radius:6px;padding:8px 14px;font-size:0.75rem;color:#000000;margin-bottom:8px'>"
        f"<b>Your Account: ${_pb_bal:,.0f} · {_pb_tier_name}</b>"
        f" &nbsp;·&nbsp; Risk budget this trade: <b>${_pb_risk_usd:,.0f}</b>"
        f" &nbsp;·&nbsp; ~{_pb_contracts} contract(s) at an assumed $0.50 premium "
        f"(cost ≈ ${_pb_position_cost:,.0f})"
        f" &nbsp;·&nbsp; Stage-1 profit if hit: <b>+${_pb_s1_profit:,.0f}</b>"
        f" &nbsp;·&nbsp; Max loss if stopped: <b>−${_pb_max_loss:,.0f}</b>"
        f"</div>",
        unsafe_allow_html=True,
    )

    # ── "How This Becomes a Trade" — contract mechanics primer ───────────────
    # Direct response to user feedback: "I have no clue the entry price exit
    # price contract price strike price... how would I know the right
    # contract to enter, strike price, date." Every number below is read
    # directly from the bot's real selection/exit code (trading_logic.py
    # select_contract(), risk.py RiskManager, config.py) — not invented.
    # 2026-06-20 — direct user feedback: this block was "a massive block of
    # text sitting above the lab... forces the user to read a manual before
    # they can even look at the chart, which ruins the cockpit feel." Moved
    # into a collapsed-by-default expander so the page opens straight onto
    # the active strategy + the "Watch It Happen" lab — the reference
    # material is one click away instead of blocking the view. (A true
    # hover-triggered overlay isn't a robust native Streamlit pattern —
    # st.expander is the equivalent "on demand, not in the way" affordance
    # that doesn't depend on fragile custom CSS/JS.)
    with st.expander("📋 How a Signal Becomes an Actual Trade — open for the contract-mechanics reference", expanded=False):
        st.caption(
            "This is the SAME process for all 8 strategies below — only the underlying "
            "price signal changes tab to tab. This is what happens once any of them fires."
        )

        # ── Macro step-tracker — 2026-06-20, direct user feedback: treat this
        # section "as a progress tracker rather than just a list of rules" so
        # it reads as a pipeline (signal -> contract -> filters -> size ->
        # exit) instead of four disconnected boxes, bridging into the
        # "Watch It Happen" lab below.
        _hbt_stages = [
            ("1", "Pick the\nContract", "#3b82f6"),
            ("2", "Clear 4\nFilters", "#f59e0b"),
            ("3", "Position\nSize", "#22c55e"),
            ("4", "Exit\nPlan", "#ef4444"),
        ]
        _stepper_parts = ["<div style='display:flex;align-items:center;margin:8px 0 18px 0'>"]
        for _i, (_num, _stage_label, _color) in enumerate(_hbt_stages):
            _stepper_parts.append(
                "<div style='display:flex;flex-direction:column;align-items:center;min-width:80px'>"
                f"<div style='width:36px;height:36px;border-radius:50%;background:{_color};"
                "color:#ffffff;display:flex;align-items:center;justify-content:center;"
                f"font-weight:800;font-size:1rem;box-shadow:0 0 0 4px {_color}22'>{_num}</div>"
                "<div style='font-size:0.72rem;font-weight:700;margin-top:6px;text-align:center;"
                f"color:#111827;white-space:pre-line'>{_stage_label}</div>"
                "</div>"
            )
            if _i < len(_hbt_stages) - 1:
                _stepper_parts.append(
                    "<div style='flex:1;height:2px;background:#d1d5db;margin:0 4px;"
                    "align-self:flex-start;margin-top:17px'></div>"
                )
        _stepper_parts.append("</div>")
        st.markdown("".join(_stepper_parts), unsafe_allow_html=True)

        _hbt_col1, _hbt_col2 = st.columns(2)
        with _hbt_col1:
            st.markdown(
                "<div style='background:rgba(59,130,246,0.08);border-left:3px solid #3b82f6;"
                "padding:10px 12px;border-radius:4px;font-size:0.85rem;height:100%'>"
                "<b>① Pick the contract</b><br><br>"
                "<b>Direction:</b> bullish signal → CALL · bearish signal → PUT<br><br>"
                "<b>Expiration:</b> the nearest listed expiration date that's "
                "<b>7–21 days out</b> — Tradier returns these sorted soonest-first, and the "
                "bot tries them in that order, only skipping to a farther date if the "
                "nearer one has no usable chain data.<br><br>"
                "<b>Strike:</b> the <b>first strike price out-of-the-money</b> from the "
                "current stock price — for a CALL, the cheapest strike just <i>above</i> "
                "price; for a PUT, the cheapest strike just <i>below</i> it. "
                "<b>Not at-the-money</b> — one step further out, because it's cheaper and "
                "more liquid."
                "</div>",
                unsafe_allow_html=True,
            )
        with _hbt_col2:
            # ── Filter pipeline — 2026-06-20: these four checks are run IN
            # SEQUENCE on each candidate contract, so a horizontal row of
            # connected checkpoints shows that "path from signal to entry"
            # directly, instead of a flat bulleted list that reads as four
            # unrelated facts.
            _filter_chips = [
                ("💲", "Price", "$0.05 – $10.00"),
                ("💰", "Budget", "ask × 100 ≤ risk budget"),
                ("↔️", "Spread", "≤ $0.50"),
                ("💧", "Liquidity", "OI ≥ 150"),
            ]
            _chip_parts = ["<div style='display:flex;align-items:center;gap:4px;flex-wrap:wrap;margin-bottom:10px'>"]
            for _ci, (_icon, _name, _detail) in enumerate(_filter_chips):
                _chip_parts.append(
                    "<div style='background:#ffffff;border:1.5px solid #f59e0b;border-radius:20px;"
                    "padding:5px 11px;font-size:0.72rem;white-space:nowrap'>"
                    f"<b>{_icon} {_name}</b><br><span style='color:#6b7280'>{_detail}</span></div>"
                )
                if _ci < len(_filter_chips) - 1:
                    _chip_parts.append("<span style='color:#9ca3af;font-weight:700'>→</span>")
            _chip_parts.append("</div>")

            st.markdown(
                "<div style='background:rgba(245,158,11,0.08);border-left:3px solid #f59e0b;"
                "padding:10px 12px;border-radius:4px;font-size:0.85rem;height:100%'>"
                "<b>② The contract has to clear 4 filters</b><br><br>"
                + "".join(_chip_parts) +
                "If nothing in the chain clears all four, the bot skips the trade — it "
                "does not loosen the filters to force an entry."
                "</div>",
                unsafe_allow_html=True,
            )

        st.markdown("")
        st.markdown(
            "<div style='background:rgba(34,197,94,0.08);border-left:3px solid #22c55e;"
            "padding:10px 12px;border-radius:4px;font-size:0.85rem'>"
            "<b>③ Position size</b> — how many contracts: "
            f"<code>risk budget ÷ (premium × {_PB_STOP_PCT:.0%} × 100)</code>, rounded down, "
            "minimum 1 if affordable. The 20% in that formula is the hard stop below — "
            "you're never risking the full premium, only the slice you'd lose if the "
            "stop fires."
            "</div>",
            unsafe_allow_html=True,
        )

        st.markdown("")
        st.markdown("**④ The exit plan — same for every contract, decided in advance:**")
        st.markdown(
            "<div style='display:flex;gap:10px;flex-wrap:wrap;font-size:0.82rem'>"
            f"<div style='flex:1;min-width:140px;background:rgba(239,68,68,0.10);"
            f"border-radius:6px;padding:8px 10px'><b>🛑 Hard Stop</b><br>"
            f"−{_PB_STOP_PCT:.0%} of premium<br><span style='color:#9ca3af'>exits "
            f"automatically, no exceptions</span></div>"
            f"<div style='flex:1;min-width:140px;background:rgba(245,158,11,0.10);"
            f"border-radius:6px;padding:8px 10px'><b>⏱️ Early Stop</b><br>"
            f"−12% within first 20 min<br><span style='color:#9ca3af'>kills slow fails "
            f"before they become full stops</span></div>"
            f"<div style='flex:1;min-width:140px;background:rgba(34,197,94,0.10);"
            f"border-radius:6px;padding:8px 10px'><b>✅ Stage 1</b><br>"
            f"+{_PB_STAGE1_GAIN:.0%} → sell half<br><span style='color:#9ca3af'>locks in "
            f"profit, lets the rest ride</span></div>"
            f"<div style='flex:1;min-width:140px;background:rgba(59,130,246,0.10);"
            f"border-radius:6px;padding:8px 10px'><b>📈 Stage 2 Trail</b><br>"
            f"remaining half trails to +{_PB_STAGE2_TRAIL:.0%}<br><span style='color:#9ca3af'>"
            f"floor moves up, never back to break-even</span></div>"
            f"<div style='flex:1;min-width:140px;background:rgba(168,85,247,0.10);"
            f"border-radius:6px;padding:8px 10px'><b>⏰ Time-Box</b><br>"
            f"20 min if flat/losing<br>45 min if winning<br><span style='color:#9ca3af'>"
            f"theta decay caps how long a stale trade gets held</span></div>"
            f"<div style='flex:1;min-width:140px;background:rgba(107,114,128,0.10);"
            f"border-radius:6px;padding:8px 10px'><b>🔚 3:55 PM Cutoff</b><br>"
            f"everything closes<br><span style='color:#9ca3af'>no overnight risk, ever, "
            f"on any position</span></div>"
            "</div>",
            unsafe_allow_html=True,
        )
        st.caption(
            f"A {_PB_SLIPPAGE:.0%} slippage buffer is built into entry and profit-target "
            f"math throughout — the bot assumes its fill will be slightly worse than the "
            f"quoted price, rather than hoping for a perfect fill."
        )

    # ═══════════════════════════════════════════════════════════════════════
    # PLAYBOOKS LESSON SYSTEM (2026-06-20 redesign)
    # ═══════════════════════════════════════════════════════════════════════
    # Why this exists: the previous version was a flat stack of a markdown
    # paragraph, a rules table, a chart, and a caption — repeated 8 times with
    # no visual structure tying them together. Direct user feedback: "I'm not
    # sure what I'm looking at... it doesn't tell me anything." This rebuilds
    # every strategy tab as a consistent 4-part LESSON (Idea -> Rules -> Watch
    # It Happen -> Common Mistake/Pro Tip) so it reads as a course module, not
    # a chart dump — and the "Watch It Happen" examples now explicitly explain
    # WHY the signal fired, WHY the entry is one bar later, and WHAT the real
    # outcome was, using each example's actual stored numbers (RVOL,
    # confidence, direction, outcome) rather than generic boilerplate.

    # ── Helper: render a strategy reference card ─────────────────────────────
    def _strat_card(rows: list[tuple], color: str = "#0969da") -> None:
        """Render a two-column (Condition / Detail) reference table."""
        html = (
            "<table style='width:100%;border-collapse:collapse;font-size:0.82rem;'>"
            "<thead><tr>"
            f"<th style='text-align:left;padding:5px 8px;border-bottom:2px solid {color};color:#1f2328;width:38%'>Condition</th>"
            f"<th style='text-align:left;padding:5px 8px;border-bottom:2px solid {color};color:#1f2328;'>Detail</th>"
            "</tr></thead><tbody>"
        )
        for i, (cond, detail) in enumerate(rows):
            bg = "#f6f8fa" if i % 2 == 0 else "#ffffff"
            html += (
                f"<tr style='background:{bg}'>"
                f"<td style='padding:5px 8px;font-weight:600;color:#1f2328;border-bottom:1px solid #eaecef'>{cond}</td>"
                f"<td style='padding:5px 8px;color:#57606a;border-bottom:1px solid #eaecef'>{detail}</td>"
                "</tr>"
            )
        html += "</tbody></table>"
        st.markdown(html, unsafe_allow_html=True)

    _pb_tabs = st.tabs([
        "1 · Range Break",
        "2 · Structure Shift",
        "3 · VWAP Pullback",
        "4 · Fair Value Gap",
        "5 · Mid-Day Break",
        "6 · Afternoon Reversal",
        "7 · Trend Continuation",
        "8 · Channel Rejection",
        "9 · Trading Log Explanations",
    ])

    # ── Real-example rendering (2026-06-20 Playbooks overhaul) ───────────────
    # Replaces _gen_orb_scenario()/_build_orb_fig()/_build_strategy_fig() —
    # those generated FABRICATED random candles (see git history / audit notes
    # if still present below). A paid education product showing made-up charts
    # to "prove" a strategy works is a credibility problem, not a polish nit.
    # playbook_examples.py mines genuine historical fires by running real bars
    # through the actual production strategy-evaluation functions; this block
    # renders whatever real examples exist via TradingView's own open-source
    # Lightweight Charts library (lightweight_chart.py) instead of Plotly.
    from playbook_examples import load_examples as _pb_load_examples
    from lightweight_chart import render_strategy_chart as _pb_render_chart

    _pb_examples = _pb_load_examples()

    # ── Strategy metadata — single source of truth for all 8 lesson tabs ─────
    # FIX 2026-06-20: every rules table here was re-verified line-by-line
    # against the CURRENT code in strategy_router.py — not against this
    # codebase's own docstrings, which have drifted from the real logic
    # several times (e.g. CHAN_BREAK's docstring claims "RVOL >= 1.3x" but
    # the code actually calls a dynamic-threshold function that resolves to
    # 1.0x; MID_BRK's docstring window doesn't match its actual bar_min
    # check; BOS_MSS's docstring never mentions its real FVG-confirmation
    # requirement). User feedback that triggered this: a real example showed
    # "RVOL hit 1.01x (needs >=1.3x)" passing anyway — that's not a fluke,
    # it's this exact gap. gate_rvol below is now only a DISPLAY FALLBACK for
    # cached examples that predate the rvol_gate field — the real per-example
    # explanation panel uses the live re-derived value (see
    # playbook_examples.py's _real_rvol_gate()).
    #
    # 4 of these 8 strategies (INST_ORB, VWAP_PB, MID_BRK, CHAN_BREAK) use a
    # DYNAMIC gate, not a fixed percentage: it defaults to 1.2x RVOL, but
    # drops to 1.0x the moment market structure already confirms the same
    # direction — the reasoning being that confirmed structure IS the edge,
    # so it needs less raw volume to trust. Their rules tables say "Dynamic"
    # and explain this in one line rather than quoting a single fixed number
    # that would be wrong roughly half the time.
    _PB_STRATEGIES = [
        {
            "id": "INST_ORB", "icon": "🚀", "color": "#f59e0b",
            "title": "Institutional Opening Range Breakout",
            "hook": "The highest-confidence setup — fires earliest in the session.",
            "concept": (
                "The opening range (OR) is the first 5-minute candle. When price closes convincingly "
                "above OR High with elevated volume and price is above VWAP, institutions are buying "
                "the breakout. Below OR Low with the same criteria = PUT."
            ),
            "gate_rvol": 1.2, "max_examples": 3,
            "rules": [
                ("Trigger",          "Close above OR High (CALL) · close below OR Low (PUT)"),
                ("Time Window",      "09:30 – 10:30 ET · first hour only"),
                ("Volume Gate",      "Dynamic: 1.2× RVOL by default, drops to 1.0× if structure already confirms this direction · PLUS raw volume > 1.5× its 20-bar average"),
                ("VWAP Gate",        "Price must be above VWAP for CALL · below VWAP for PUT"),
                ("Confidence Range", "0.85 – 0.95 (highest of all 8 strategies)"),
                ("Flip Trigger",     "Hard stop (−20%) only → arms an immediate opposite-direction entry if the other side of the range is breaking with volume still confirmed"),
            ],
            "common_mistake": "Entering the moment price pokes above the OR boundary. The bot waits for the candle to CLOSE above it with volume already confirmed — that patience is most of the edge.",
            "pro_tip": "If price breaks the OR one way but the broader trend (MSA) already points the other way, the bot FLIPS direction on entry — that's a failed-breakout fade, not a mistake.",
        },
        {
            "id": "BOS_MSS", "icon": "🔀", "color": "#818cf8",
            "title": "Break of Structure / Market Structure Shift",
            "hook": "Requires proof from two different angles at once — structure AND a real imbalance.",
            "concept": (
                "Price makes Lower Highs and Lower Lows (downtrend) or Higher Highs and Higher Lows "
                "(uptrend). A Break of Structure (BOS) happens when price takes out the most recent swing "
                "low in a downtrend — confirming the move. A Market Structure Shift (MSS) is the first BOS "
                "after consolidation, signaling a new directional leg."
            ),
            "gate_rvol": 1.5, "max_examples": 2,
            "rules": [
                ("Trigger",       "Lower Low then close breaks above prior swing high (bullish) · Higher High then close breaks below prior swing low (bearish)"),
                ("Time Window",   "No restriction — can fire any time there's enough data (≥6 bars)"),
                ("Volume Gate",   "RVOL ≥ 150% on the break candle — fixed, not dynamic"),
                ("Imbalance Gate","Requires a CONFIRMED Fair Value Gap in the same direction within the recent session — structure alone isn't enough"),
                ("Trend Filter",  "Close must be on the correct side of EMA50"),
                ("Confidence Range", "0.70 – 0.88"),
            ],
            "common_mistake": "Entering on the LL/HH label itself — the entry is when price BREAKS past the prior swing extreme, one bar later, not at the label. Also: structure alone never qualifies — without a confirmed FVG too, the bot skips it.",
            "pro_tip": "When you see SH → LH → SL → LL annotations descending in a stair-step, the bot is tracking a confirmed downtrend — but it still needs the FVG before it acts on it.",
        },
        {
            "id": "VWAP_PB", "icon": "🎯", "color": "#06b6d4",
            "title": "VWAP Pullback",
            "hook": "Buying value, not chasing momentum.",
            "concept": (
                "VWAP (Volume Weighted Average Price) is the average price paid all day, weighted by "
                "volume. Institutions treat it as a fair-value line — buy below it, sell above it. In an "
                "uptrend, when price dips back to VWAP and forms a Higher Low, that's the institutional "
                "buy zone."
            ),
            "gate_rvol": 1.2, "max_examples": 2,
            "rules": [
                ("Trigger",       "Price touches VWAP from above (uptrend) or below (downtrend) and closes back in trend direction"),
                ("Time Window",   "09:45 ET onward — no upper bound, can fire through the close"),
                ("Volume Gate",   "Dynamic: 1.2× RVOL by default, drops to 1.0× if structure already confirms this direction"),
                ("Trend Filter",  "Price AND VWAP both above EMA50 for bullish · both below for bearish"),
                ("Confidence Range", "0.60 – 0.82"),
            ],
            "common_mistake": "Treating any touch of VWAP as a signal. If price CLOSES through VWAP on the touch candle (not just wicks it), the setup fails — the bot skips it.",
            "pro_tip": "Best setups occur when price has been trending for 30+ minutes and this is the SECOND VWAP test, not the first.",
        },
        {
            "id": "FVG", "icon": "🕳️", "color": "#ec4899",
            "title": "Fair Value Gap",
            "hook": "Price always seems to come back and fill the hole it left behind.",
            "concept": (
                "A Fair Value Gap is a 3-candle imbalance — candle 1's high sits below candle 3's low, "
                "leaving a zone that was never properly traded. It's a magnet for price. When price "
                "returns to fill the gap, institutions who missed the move are waiting there."
            ),
            "gate_rvol": 1.5, "max_examples": 2,
            "rules": [
                ("Trigger",       "Price re-enters a prior 3-bar imbalance zone (gap between candle 1 high and candle 3 low)"),
                ("Time Window",   "No restriction — can fire any time there's enough data"),
                ("Volume Gate",   "RVOL ≥ 150% on the candle entering the gap — fixed, not dynamic"),
                ("Gap Size Gate", "Gap width must be ≥ 0.5× the 14-period ATR — too small a gap is noise, not structure"),
                ("Confidence Range", "0.55 – 0.80"),
            ],
            "common_mistake": "Chasing price away from the gap. The bot doesn't — it waits for the gap to actually get revisited before entering.",
            "pro_tip": None,
        },
        {
            "id": "MID_BRK", "icon": "📉", "color": "#ef4444",
            "title": "Midday Breakdown",
            "hook": "A second-leg trade — using the morning's trend to set up an afternoon move.",
            "concept": (
                "Midday (10:30am–1:00pm) often just drifts. But if the morning already established a "
                "downtrend with a confirmed Lower High, and price finally breaks the opening range low "
                "during this window, that's a continuation — a second leg of the same idea, not a new one."
            ),
            "gate_rvol": 1.0, "max_examples": 2,
            "rules": [
                ("Trigger",       "Close breaks below OR Low · confirmed Lower High already on record"),
                ("Time Window",   "10:30 – 13:00 ET only (mid-session window)"),
                ("Volume Gate",   "Dynamic, but effectively 1.0× here — structure (Lower High) is already required, so it never needs the higher default"),
                ("Raw Volume Gate", "Current bar's volume must also exceed 1.5× its 20-bar average — a SEPARATE check from the RVOL gate above"),
                ("VWAP Gate",     "Price must be below VWAP at entry"),
                ("Confidence Range", "0.65 – 0.86"),
            ],
            "common_mistake": "Trading this setup without a pre-existing morning downtrend. Without that confirmed Lower High first, this is exactly the kind of midday trap the gate exists to avoid.",
            "pro_tip": None,
        },
        {
            "id": "AFT_REV", "icon": "🔄", "color": "#22c55e",
            "title": "Afternoon Reversal",
            "hook": "Catching institutions repositioning late in the day.",
            "concept": (
                "After a morning downtrend, sellers eventually run out of steam — shown by a Higher Low "
                "forming. When price then breaks above the most recent swing high, the downtrend "
                "structure is broken and a reversal is underway."
            ),
            "gate_rvol": None, "max_examples": 2,
            "rules": [
                ("Trigger",       "Close breaks above the most recent swing high (CALL) — Break of Structure to upside"),
                ("Time Window",   "13:00 – 15:30 ET only (afternoon window)"),
                ("Volume Gate",   "No RVOL floor at all — instead, raw volume must exceed 1.2× its 20-bar average. RVOL still affects confidence, just doesn't block entry"),
                ("Trend Context", "Must have a confirmed Higher Low before the break — proves sellers exhausted"),
                ("Confidence Range", "0.62 – 0.84"),
            ],
            "common_mistake": "Entering at the Higher Low itself, anticipating the reversal. The bot waits for proof — the actual break above the prior swing high — before committing.",
            "pro_tip": "This is the one strategy with no RVOL gate at all — don't assume every entry had 'high volume'; check the real RVOL shown per example, it's often just average.",
        },
        {
            "id": "TREND_CONT", "icon": "➡️", "color": "#8b5cf6",
            "title": "Trend Continuation",
            "hook": "The professional re-entry — pulling back into a trend instead of chasing it.",
            "concept": (
                "Once a trend is established, the smart re-entry is on a pullback, not the initial move "
                "everyone already saw. In a downtrend, price pulls back to form a Lower High, then "
                "resumes lower — the bot enters when that pullback fails."
            ),
            "gate_rvol": 1.2, "max_examples": 2,
            "rules": [
                ("Trigger",       "Downtrend: close < LH bar close after confirmed LH (PUT) · Uptrend: close > HL bar close after confirmed HL (CALL)"),
                ("Time Window",   "09:45 – 14:30 ET"),
                ("Volume Gate",   "RVOL ≥ 120% — fixed, not dynamic (lower gate since the trend is already established)"),
                ("Recency Gate",  "The Lower High / Higher Low being re-entered must be within the last 20 bars — older pullbacks are considered stale"),
                ("VWAP Gate",     "Price below VWAP for PUT · above VWAP for CALL"),
                ("Confidence Range", "0.65 – 0.82"),
            ],
            "common_mistake": "Chasing the initial breakout everyone else already saw. This setup specifically waits for the FIRST pullback to fail instead.",
            "pro_tip": "The lower volume gate (1.2×) is intentional — the trend is already proven, so less new participation is needed to sustain it.",
        },
        {
            "id": "CHAN_BREAK", "icon": "📐", "color": "#f97316",
            "title": "Channel Trendline Rejection",
            "hook": "The most precise setup in the system — and the highest confidence ceiling.",
            "concept": (
                "When price makes two or more Lower Highs, a descending trendline can be drawn through "
                "them — dynamic resistance. Every time price tags it and rejects, that's a short "
                "opportunity. The bot projects the line forward in real time."
            ),
            "gate_rvol": 1.0, "max_examples": 2,
            "rules": [
                ("Trigger",       "Current bar's high tags within 0.3% of the projected trendline · closes back below it"),
                ("Time Window",   "09:45 – 14:00 ET"),
                ("Volume Gate",   "Dynamic, but effectively 1.0× here — a verified 2-swing channel IS treated as confirmed structure"),
                ("Channel Requirement", "≥ 2 confirmed swing highs forming the descending line · both within last 40 bars · slope steep enough to not be flat/choppy"),
                ("Confidence Range", "0.75 – 0.90 (highest ceiling of all strategies)"),
            ],
            "common_mistake": None,
            "pro_tip": "By the time price has rejected the same line two or three times, the pattern is about as proven as it gets intraday.",
        },
    ]

    def _outcome_badge(outcome: str) -> tuple[str, str, str, str]:
        """Returns (icon, label, accent_color, plain-language explanation)."""
        return {
            "clean_win": ("🟢", "Favorable follow-through", "#16a34a",
                          "Price moved favorably after this signal — this is what a working setup looks like."),
            "reversed":  ("🔴", "Reversed against the signal", "#dc2626",
                          "Price moved against the signal — this is what getting stopped out looks like in real conditions."),
            "chopped":   ("⚪", "Chopped — limited follow-through", "#6b7280",
                          "Price didn't move much either way. A real, unexciting result — most signals look like this; "
                          "the edge comes from cutting losers fast, not every trade being a big winner."),
        }.get(outcome, ("⚪", "Outcome unclear", "#6b7280", ""))

    def _step_slider(key: str, delta: int, lo: int, hi: int) -> None:
        """Move a reveal-slider's value by delta, clamped to [lo, hi].
        Button on_click callbacks run BEFORE the rest of the script reruns
        and the slider widget redraws, so mutating session_state[key] here
        is the standard, safe Streamlit pattern for buttons driving a keyed
        slider's value (mutating it any other way/time is a no-op)."""
        cur = st.session_state.get(key, hi)
        st.session_state[key] = max(lo, min(hi, cur + delta))

    def _toggle_play(play_key: str, slider_key: str, lo: int, hi: int) -> None:
        """on_click callback for the Play/Pause button.

        BUG FIX 2026-06-20: this used to be inline logic inside a plain
        `if st.button(...):` check, placed in the transport bar's 4th
        column — AFTER the slider widget (3rd column) had already been
        instantiated in that same script pass. Streamlit raises
        StreamlitAPIException if you mutate a widget's session_state value
        after that widget has already been created in the current run.
        on_click callbacks run BEFORE the script reruns and recreates the
        slider, so mutating session_state[slider_key] here is the safe,
        standard pattern — same reasoning as _step_slider above, just for
        the "restart from the top when Play is pressed at the end" case.
        """
        now_playing = not st.session_state.get(play_key, False)
        if now_playing and st.session_state.get(slider_key, hi) >= hi:
            st.session_state[slider_key] = lo
        st.session_state[play_key] = now_playing
        _force_full_rerun()

    def _force_full_rerun() -> None:
        """Escalate a fragment-scoped rerun to a full app rerun.

        2026-06-20 — needed for real autoplay: each example's cockpit lives
        in an st.fragment whose run_every interval is only set when that
        example is actively playing. Toggling Play/Pause changes whether
        run_every should be active at all, but a normal click inside a
        fragment only reruns the fragment, not the whole page — so the
        fragment never gets re-decorated with the new interval. Forcing a
        full rerun on every Play/Pause press (and when autoplay naturally
        reaches the end) is what actually starts/stops the timer.
        scope="app" requires a reasonably recent Streamlit; fall back to a
        plain rerun on older versions rather than crashing the page.
        """
        try:
            st.rerun(scope="app")
        except TypeError:
            st.rerun()

    # Cockpit card chrome — white background, thick black border, sharp
    # corners. Replaces the earlier soft colored-tint cards: direct mockup
    # feedback asked for a "sleek, high-contrast, $500/month research
    # terminal" feel, which reads as thick black borders on white, not
    # pastel left-accent strips.
    _CARD_BORDER = "#111827"

    # ── "Lab" frame CSS — 2026-06-20, direct user feedback: "use a 2px solid
    # black border around that central chart lab to give it the proprietary
    # research terminal weight." Each example's transport bar + chart used to
    # be two separately-bordered pieces stacked on top of each other; this
    # wraps them in ONE st.container(key=...) per example and targets all of
    # them at once with a single attribute-contains selector, so the whole
    # center column reads as one unified terminal panel, not two stacked
    # boxes. Injected once per script run, not per example — duplicate
    # <style> tags are harmless, but there's no reason to repeat it ~20x.
    st.markdown(
        f"<style>div[class*='st-key-pb_lab_'] {{"
        f"border:2px solid {_CARD_BORDER} !important;"
        f"border-radius:10px !important;"
        f"background:#fafafa !important;"
        f"box-shadow:0 2px 10px rgba(0,0,0,0.10);"
        f"padding:6px 6px 2px 6px !important;"
        f"}}</style>",
        unsafe_allow_html=True,
    )

    def _cockpit_card(header_icon: str, header_text: str, lines: list[str],
                       accent_color: str | None = None, is_active: bool = False) -> str:
        """Build one numbered cockpit card — white bg, 2px black border,
        a bold header row, and plain numbered steps (mirrors the mockup's
        '1. 2. 3.' reference-card style) instead of a wall of prose.

        is_active (2026-06-20 — direct user feedback: "when the student
        drags to frame 3, the right panel should ... highlight 'the
        signal' logic specifically for that candle"): the card matching
        wherever the transport bar currently sits gets a colored glow +
        a "● LIVE" badge instead of the plain black border, so the right
        panel visibly tracks the slider/autoplay instead of three
        equal-weight boxes that all looked alike once revealed."""
        items = "".join(f"<div style='margin-top:4px'>{i+1}. {line}</div>" for i, line in enumerate(lines))
        border_color = accent_color if (is_active and accent_color) else _CARD_BORDER
        glow = f"box-shadow:0 0 0 3px {accent_color}33;" if (is_active and accent_color) else ""
        live_badge = (
            f"<span style='background:{accent_color};color:#fff;font-size:0.6rem;font-weight:800;"
            f"letter-spacing:0.04em;padding:1px 7px;border-radius:10px;margin-left:8px;"
            f"vertical-align:middle'>● LIVE</span>"
        ) if (is_active and accent_color) else ""
        return (
            f"<div style='background:#ffffff;border:2px solid {border_color};{glow}"
            f"border-radius:6px;padding:10px 12px;margin-bottom:10px;"
            f"font-size:0.82rem;color:#111827;transition:box-shadow 0.2s'>"
            f"<div style='font-weight:800;letter-spacing:0.02em;margin-bottom:2px'>"
            f"{header_icon} {header_text}{live_badge}</div>{items}</div>"
        )

    def _pending_card(header_icon: str, header_text: str, note: str) -> str:
        """A 'not revealed yet' state for the Entry/Outcome cards — dashed
        grey border instead of solid black, so the right panel visibly
        reacts to where the transport bar actually is (added 2026-06-20:
        previously these cards always showed the full answer regardless of
        which candle was revealed, which defeats the point of a step-through
        simulator)."""
        return (
            f"<div style='background:#f9fafb;border:2px dashed #9ca3af;"
            f"border-radius:6px;padding:10px 12px;margin-bottom:10px;"
            f"font-size:0.82rem;color:#6b7280'>"
            f"<div style='font-weight:800;letter-spacing:0.02em;margin-bottom:2px'>"
            f"{header_icon} {header_text}</div>⏳ {note}</div>"
        )

    def _render_example_block(meta: dict, ex: dict, ex_i: int) -> None:
        """One real example: a 'cockpit' — chart + frame-step transport bar
        on the left, white/black-bordered Signal/Entry/Outcome cards on the
        right — built from this example's actual stored numbers, not
        generic text.

        2026-06-20 overhaul, direct user feedback:
        - "if i click play it should play not go to the next bar" — Play
          now drives a real timer (st.fragment(run_every=...)) instead of
          stepping once. See _force_full_rerun()'s docstring for why the
          whole cockpit has to live inside that fragment.
        - "I need this ON the chart not on the side of it" — short
          plain-language notes now render as floating callouts anchored to
          the signal/entry/exit candles themselves (lightweight_chart.py),
          in addition to the fuller side cards.
        - "explanations are all tech jargon ... as if written by AI" — every
          jargon term (RVOL, VWAP, confidence, swing pivot) in the side
          cards now carries an inline plain-English gloss instead of being
          dropped on the reader bare.
        """
        bars = ex["bars"]
        icon, label, accent, _ = _outcome_badge(ex["outcome"])
        st.markdown(f"**{ex['ticker']} · {ex['date']}** — {icon} {label}")

        slider_key = f"pb_reveal_{meta['id']}_{ex_i}"
        play_key = f"{slider_key}_playing"
        lo = min(ex["signal_idx"] + 1, len(bars))
        hi = len(bars)
        if slider_key not in st.session_state:
            st.session_state[slider_key] = hi
        if play_key not in st.session_state:
            st.session_state[play_key] = False

        # run_every is only set to a real interval while THIS example is
        # actively playing — computed here, in the OUTER (non-fragment)
        # scope, so a full rerun (forced below whenever Play/Pause is
        # pressed, or when autoplay naturally hits the end) always picks up
        # the current state and (re)builds the fragment with the right
        # timer. An idle example costs nothing extra: run_every=None means
        # no periodic reruns at all.
        _interval = "0.55s" if st.session_state.get(play_key, False) else None

        # ── Plain-language notes, built once, shared by the on-chart
        # callouts AND the side cards below. Computed from this example's
        # real stored numbers — nothing here is invented per-example text.
        direction_word = "Bullish (CALL)" if ex["direction"] == "bullish" else "Bearish (PUT)"
        _gate = ex.get("rvol_gate", meta.get("gate_rvol"))
        _gate_text = f"needs ≥{_gate:.1f}×" if _gate is not None else "no fixed RVOL floor on this setup"
        _, _, _, outcome_text = _outcome_badge(ex["outcome"])

        _vwap_series_ex = ex.get("vwap") or []
        _sig_i = ex["signal_idx"]
        _vwap_side, _vwap_val = None, None
        if _sig_i < len(_vwap_series_ex) and _vwap_series_ex[_sig_i] is not None:
            _sig_close = bars[_sig_i]["close"]
            _vwap_val = _vwap_series_ex[_sig_i]
            _vwap_side = "above" if _sig_close > _vwap_val else "below"

        _signal_note = (
            f"Trading was <b>{ex['rvol']:.1f}× busier</b> than a normal moment here"
            + (f", while price sat <b>{_vwap_side} the day's average price</b>" if _vwap_side else "")
            + " — that combination is what made the bot start watching this move."
        )
        _entry_word = "call" if ex["direction"] == "bullish" else "put"
        _entry_note = (
            f"The bot never buys on the signal candle — it waits one full candle to confirm the move is "
            f"real, then buys a <b>{_entry_word}</b> at the very next open."
        )
        _exit_note = {
            "clean_win": "Price kept moving the way the bot bet — a clean win.",
            "reversed":  "Price turned around and went the other way — this trade got stopped out.",
            "chopped":   "Price went sideways without real follow-through — a flat, unexciting result.",
        }.get(ex["outcome"], outcome_text)

        @st.fragment(run_every=_interval)
        def _cockpit() -> None:
            # ── Autoplay tick — only does anything while play_key is True.
            # Reads/writes session_state[slider_key] BEFORE the slider
            # widget below is created, which is the standard safe way to
            # drive a keyed widget's value programmatically in Streamlit.
            if st.session_state.get(play_key, False):
                cur = st.session_state.get(slider_key, lo)
                if cur >= hi:
                    # Reached the end on its own — stop for real (force a
                    # full rerun so the fragment gets rebuilt with
                    # run_every=None, not just left ticking uselessly).
                    st.session_state[play_key] = False
                    _force_full_rerun()
                else:
                    st.session_state[slider_key] = cur + 1

            chart_col, explain_col = st.columns([2, 1])

            with chart_col:
                # ── One unified "lab" frame — 2026-06-20, direct user
                # feedback: "use a 2px solid black border around that
                # central chart lab to give it the proprietary research
                # terminal weight." Previously the transport bar and the
                # chart were two separately-bordered pieces stacked on top
                # of each other; wrapping both in ONE st.container(key=...)
                # and targeting that key's class with scoped CSS (injected
                # once, above) makes the whole center column read as one
                # bordered terminal panel. Scoped to st-key-pb_lab_* only —
                # deliberately NOT a bare `.stVerticalBlock` selector, which
                # is shared by every vertical container in the whole app
                # (sidebar included) and would slap a black border on
                # things far outside this page.
                with st.container(border=True, key=f"pb_lab_{slider_key}"):
                    chart_slot = st.empty()

                    _t1, _t2, _t3, _t4, _t5 = st.columns([1, 1, 7, 1, 1])
                    with _t1:
                        st.button("⏮", key=f"{slider_key}_first", help="Jump to start",
                                  use_container_width=True,
                                  on_click=_step_slider, args=(slider_key, -100_000, lo, hi))
                    with _t2:
                        st.button("◀", key=f"{slider_key}_prev", help="Step back one candle",
                                  use_container_width=True,
                                  on_click=_step_slider, args=(slider_key, -1, lo, hi))
                    with _t3:
                        reveal = st.slider(
                            "Step through the candles", min_value=lo, max_value=hi,
                            key=slider_key, label_visibility="collapsed",
                        )
                    with _t4:
                        _playing_now = st.session_state.get(play_key, False)
                        _play_label = "⏸" if _playing_now else "▶"
                        _play_help = "Pause" if _playing_now else "Play — watch it build automatically"
                        # on_click (not a plain `if st.button():`) — see
                        # _toggle_play()'s docstring: this button sits AFTER
                        # the slider in the same row, so any inline mutation
                        # of session_state[slider_key] here would hit
                        # Streamlit's "modified after instantiation" error.
                        st.button(_play_label, key=f"{slider_key}_play", help=_play_help,
                                  use_container_width=True,
                                  on_click=_toggle_play, args=(play_key, slider_key, lo, hi))
                    with _t5:
                        st.button("⏭", key=f"{slider_key}_last", help="Jump to end",
                                  use_container_width=True,
                                  on_click=_step_slider, args=(slider_key, 100_000, lo, hi))
                    _word = "Playing" if st.session_state.get(play_key, False) else "Frame"
                    st.caption(
                        f"{_word} {reveal - lo + 1} of {hi - lo + 1} — "
                        f"press ▶ to watch it build automatically, or drag the bar"
                    )

                    with chart_slot.container():
                        _pb_render_chart(
                            bars=bars, signal_idx=ex["signal_idx"], entry_idx=ex["entry_idx"],
                            exit_idx=ex["exit_idx"], outcome=ex["outcome"], ticker=ex["ticker"],
                            date_str=ex["date"], direction=ex["direction"], reveal_count=reveal,
                            # .get(...) — older cached examples (pre-overlay schema) just
                            # omit these and the chart renders without them, no crash.
                            vwap=ex.get("vwap"), or_high=ex.get("or_high"), or_low=ex.get("or_low"),
                            swing_points=ex.get("swing_points"),
                            # On-chart callouts only appear once the transport bar has
                            # actually reached that candle — same progressive-reveal
                            # logic as the side cards below, just rendered on the chart.
                            signal_note=_signal_note if reveal >= ex["signal_idx"] + 1 else None,
                            entry_note=_entry_note if reveal >= ex["entry_idx"] + 1 else None,
                            exit_note=_exit_note if reveal >= ex["exit_idx"] + 1 else None,
                        )

            with explain_col:
                signal_lines = [
                    f"<b>Volume check (RVOL):</b> trading was <b>{ex['rvol']:.2f}× busier</b> than a normal "
                    f"moment ({_gate_text}). High RVOL means real money is moving, not just noise — the bot "
                    f"won't act on a quiet tape.",
                    f"<b>Confidence score:</b> the bot rated this setup <b>{ex['confidence']:.2f} out of 1.00</b> "
                    f"— a rough 'how cleanly did this match the pattern' score, not a guarantee of the outcome.",
                    f"<b>Direction:</b> read as a <b>{direction_word}</b> setup, so the bot would buy a "
                    f"{_entry_word} option — the kind that profits if price "
                    f"{'rises' if ex['direction']=='bullish' else 'falls'}.",
                ]
                if _vwap_side:
                    signal_lines.append(
                        f"<b>VWAP check:</b> price was trading <b>{_vwap_side} VWAP</b> (${_vwap_val:.2f}) — "
                        f"VWAP is the average price everyone has paid today, so this tells the bot which side "
                        f"of 'fair value' the stock is leaning toward."
                    )

                if ex.get("or_high") is not None or ex.get("or_low") is not None:
                    _parts = []
                    if ex.get("or_high") is not None:
                        _parts.append(f"High ${ex['or_high']:.2f}")
                    if ex.get("or_low") is not None:
                        _parts.append(f"Low ${ex['or_low']:.2f}")
                    signal_lines.append(
                        f"<b>Opening Range:</b> the first few minutes of trading set a "
                        f"{' · '.join(_parts)} (blue dashed lines on the chart) — a break above or below that "
                        f"range is one of the oldest day-trading signals there is."
                    )

                # FIX 2026-06-20: distinguish swings that EXISTED before the
                # signal fired (the actual decision basis) from ones that only
                # formed afterward (real, but couldn't have caused anything —
                # a real example had a post-entry swing low sitting right next
                # to a PUT entry, which read as "this caused the bearish call"
                # when it's chronologically impossible).
                _swing_pts = ex.get("swing_points") or []
                _pre_swings  = [s for s in _swing_pts if s.get("before_signal", True)]
                _post_swings = [s for s in _swing_pts if not s.get("before_signal", True)]
                if _pre_swings:
                    signal_lines.append(
                        f"<b>Market structure:</b> {len(_pre_swings)} swing high/low point(s) — solid purple "
                        f"▲/▼ markers — were already on the chart BEFORE this signal fired. A 'swing point' is "
                        f"just a candle that's higher (or lower) than the candles right around it; these are "
                        f"the actual pivots the bot's pattern detector is reacting to."
                    )
                if _post_swings:
                    signal_lines.append(
                        f"{len(_post_swings)} more swing pivot(s) formed AFTER the signal — the faint markers "
                        f"labeled '(after)'. Shown for context only; they came too late to have caused anything."
                    )

                # Decision-basis values the live eval function actually used,
                # straight from sig.meta — most useful when the justifying pivot
                # is a price level from EARLIER in the session than this window
                # covers, so the chart alone can't show it.
                _meta = ex.get("signal_meta") or {}
                _meta_labels = {
                    "prior_swing_high": "The prior swing high it broke above",
                    "prior_swing_low":  "The prior swing low it broke below",
                    "last_high":        "The most recent swing high on record",
                    "prev_high":        "The swing high before that",
                    "last_low":         "The most recent swing low on record",
                    "prev_low":         "The swing low before that",
                    "fvg_confirmed":    "A confirmed 'Fair Value Gap' (a price jump with no trading in between) was required for this to fire",
                }
                for _mk, _mlabel in _meta_labels.items():
                    if _mk in _meta and _meta[_mk] is not None:
                        _mv = _meta[_mk]
                        _mv_str = f"${_mv:.2f}" if isinstance(_mv, (int, float)) else str(_mv)
                        signal_lines.append(
                            f"{_mlabel}: <b>{_mv_str}</b> (this level may sit earlier in the session than "
                            f"this window shows)"
                        )

                entry_lines = [
                    "The bot never acts on the signal candle itself — it waits one full candle to confirm "
                    "the move is real, not a one-bar fluke.",
                    f"It then enters at the very next candle's <b>open</b>, buying a <b>{_entry_word}</b> "
                    f"because the setup was {direction_word.split(' ')[0].lower()}.",
                    "That one-candle delay is why the ② marker always sits one candle to the right of the "
                    "① signal on the chart.",
                ]
                outcome_lines = [outcome_text]

                # ── Progressive reveal — the panel reacts to the transport bar ──
                # `reveal` is a 1-indexed bar COUNT (reveal=N means bars[0:N] are
                # drawn, i.e. the bar at index N-1 is the last one visible). The
                # Signal card is always live (the slider's own minimum already
                # includes the signal bar — see lo above). Entry/Outcome stay in
                # a dashed "not revealed yet" state until the transport bar
                # actually reaches that candle, so stepping through (or playing)
                # the sim means something instead of always showing the answer.
                _revealed_entry = reveal >= ex["entry_idx"] + 1
                _revealed_exit  = reveal >= ex["exit_idx"] + 1

                # ── Which card is "live" right now — the frontier the
                # transport bar has most recently reached. Everything before
                # it is settled history (plain black border); everything
                # after it hasn't happened yet (dashed pending card).
                if not _revealed_entry:
                    _active_stage = "signal"
                elif not _revealed_exit:
                    _active_stage = "entry"
                else:
                    _active_stage = "outcome"

                st.markdown(
                    _cockpit_card("🟡", "THE SIGNAL", signal_lines,
                                  accent_color="#f59e0b", is_active=(_active_stage == "signal")),
                    unsafe_allow_html=True,
                )

                if _revealed_entry:
                    st.markdown(
                        _cockpit_card("🔵", "THE ENTRY", entry_lines,
                                      accent_color="#3b82f6", is_active=(_active_stage == "entry")),
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        _pending_card("🔵", "THE ENTRY", "Step forward (or press ▶) to see the entry trigger."),
                        unsafe_allow_html=True,
                    )

                if _revealed_exit:
                    st.markdown(
                        _cockpit_card(icon, "WHAT HAPPENED", outcome_lines,
                                      accent_color=accent, is_active=(_active_stage == "outcome")),
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        _pending_card("⏳", "WHAT HAPPENED", "Keep stepping forward (or pressing ▶) to watch how this one resolves."),
                        unsafe_allow_html=True,
                    )

        _cockpit()

    def _render_strategy_lesson(meta: dict) -> None:
        """Render one strategy as a cockpit-first lesson: a compact header,
        then the 'Watch It Happen' simulator (chart + transport bar + logic
        cards) as the immediate focal point, with The Idea / The Rules /
        Common Mistake / Pro Tip following below for reference.

        Reordered 2026-06-20 per direct mockup feedback: the simulator is
        the focal point a trader develops muscle memory from by stepping
        through real setups frame by frame — it shouldn't be buried below
        two cards of reading material first."""
        sid = meta["id"]

        st.markdown(
            f"<div style='display:flex;align-items:center;gap:10px;margin-bottom:6px'>"
            f"<span style='font-size:1.5rem'>{meta['icon']}</span>"
            f"<div>"
            f"<span style='font-size:1.05rem;font-weight:800;color:{meta['color']}'>{meta['title']}</span>"
            f"<span style='font-size:0.82rem;color:#9ca3af;margin-left:8px'>{meta['hook']}</span>"
            f"</div></div>",
            unsafe_allow_html=True,
        )

        # ── Cockpit: the simulator, front and center ──────────────────────
        st.markdown("##### 🎬 Watch It Happen — Real Examples")
        st.caption(
            "Real trading days, real prices — not illustrations. Step through the "
            "transport bar to watch the setup build candle by candle."
        )
        examples = _pb_examples.get(sid, [])
        if not examples:
            st.info(
                f"📭 No real example yet for **{sid}** — this strategy hasn't fired in any "
                f"session covered by the example cache. Re-run `python playbook_examples.py` "
                f"after it fires live to add a real instance here. This page deliberately "
                f"won't show a made-up chart in the meantime."
            )
        else:
            for ex_i, ex in enumerate(examples[: meta.get("max_examples", 2)]):
                if ex_i > 0:
                    st.markdown("---")
                _render_example_block(meta, ex, ex_i)

        st.markdown("---")

        # ── Reference material — scrolls below the cockpit ────────────────
        with st.container(border=True):
            st.markdown("##### 💡 The Idea")
            st.markdown(meta["concept"])

        with st.container(border=True):
            st.markdown("##### 📋 The Rules")
            _strat_card(meta["rules"], color=meta["color"])

        if meta.get("common_mistake") or meta.get("pro_tip"):
            cm_col, pt_col = st.columns(2)
            with cm_col:
                if meta.get("common_mistake"):
                    st.markdown(
                        f"<div style='background:rgba(220,38,38,0.08);border:1px solid rgba(220,38,38,0.3);"
                        f"border-radius:8px;padding:10px 14px;font-size:0.82rem;height:100%'>"
                        f"<b>⚠️ Common Mistake</b><br>{meta['common_mistake']}</div>",
                        unsafe_allow_html=True,
                    )
            with pt_col:
                if meta.get("pro_tip"):
                    st.markdown(
                        f"<div style='background:rgba(22,163,74,0.08);border:1px solid rgba(22,163,74,0.3);"
                        f"border-radius:8px;padding:10px 14px;font-size:0.82rem;height:100%'>"
                        f"<b>💎 Pro Tip</b><br>{meta['pro_tip']}</div>",
                        unsafe_allow_html=True,
                    )

    # ── Render all 8 strategy tabs from the metadata table ───────────────────
    for _pb_idx, _pb_meta in enumerate(_PB_STRATEGIES):
        with _pb_tabs[_pb_idx]:
            _render_strategy_lesson(_pb_meta)

    # ── Tab 9: Trading Log Explanations ──────────────────────────────────────
    with _pb_tabs[8]:
        from log_explanations import LOG_EXPLANATIONS

        st.markdown("**Trading Log Explanations — Plain-English Reference**")
        st.markdown(
            "Every type of message the bot can write to the Live Trading audit log, "
            "explained in plain English. Each entry shows the **keyword tag** that "
            "appears as a badge next to matching log lines in the Live Trading page — "
            "search by tag, title, category, or any word from the explanation to find "
            "what a log line means."
        )

        _log_search = st.text_input(
            "🔍 Search log explanations",
            value="",
            placeholder="e.g. TRADE_BLOCKED_LOW_RR, kill lock, R:R, Tradier...",
            key="log_explanations_search",
        ).strip().lower()

        # Category color coding — mirrors the emoji card colors used in the
        # Live Trading audit log for visual consistency.
        _cat_colors = {
            "Entries":    "#1a7f37",   # green
            "Exits":      "#0969da",   # blue
            "Risk Gates": "#bf3989",   # magenta
            "Errors":     "#cf222e",   # red
            "Scanning":   "#6e7781",   # gray
            "System":     "#9a6700",   # amber
        }

        # Filter entries by search term across tag / title / category /
        # explanation / match substrings (case-insensitive).
        if _log_search:
            _filtered = [
                e for e in LOG_EXPLANATIONS
                if _log_search in e["tag"].lower()
                or _log_search in e["title"].lower()
                or _log_search in e["category"].lower()
                or _log_search in e["explanation"].lower()
                or any(_log_search in m.lower() for m in e["match"])
            ]
        else:
            _filtered = LOG_EXPLANATIONS

        if not _filtered:
            st.warning(f"No log explanations match '{_log_search}'.")
        else:
            st.caption(f"Showing {len(_filtered)} of {len(LOG_EXPLANATIONS)} log types.")

            # Group by category, preserving first-seen order
            _cats_ordered: list[str] = []
            _by_cat: dict[str, list[dict]] = {}
            for _e in _filtered:
                _c = _e["category"]
                if _c not in _by_cat:
                    _by_cat[_c] = []
                    _cats_ordered.append(_c)
                _by_cat[_c].append(_e)

            for _cat in _cats_ordered:
                _color = _cat_colors.get(_cat, "#57606a")
                st.markdown(
                    f"<div style='margin-top:14px;margin-bottom:4px;font-weight:700;"
                    f"color:{_color};font-size:0.95rem;border-bottom:2px solid {_color};"
                    f"padding-bottom:3px'>{_cat}</div>",
                    unsafe_allow_html=True,
                )
                for _entry in _by_cat[_cat]:
                    with st.expander(f"🏷️ {_entry['tag']}  —  {_entry['title']}"):
                        st.markdown(
                            f"<span style='display:inline-block;background:{_color}1a;"
                            f"color:{_color};border:1px solid {_color};border-radius:4px;"
                            f"padding:1px 8px;font-size:0.72rem;font-weight:700;"
                            f"font-family:monospace;margin-bottom:8px'>{_entry['tag']}</span>",
                            unsafe_allow_html=True,
                        )
                        st.markdown(_entry["explanation"])
                        with st.popover("Show raw match pattern(s)"):
                            for _m in _entry["match"]:
                                st.code(_m, language=None)


# ── Price ticker bar — rendered on every page (position:fixed bottom) ─────────
_price_ticker_bar()

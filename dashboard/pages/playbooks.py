"""
dashboard/pages/playbooks.py — Strategy Playbooks page.

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
    """Render the Strategy Playbooks page."""
    st.markdown("# 📐  Strategy Playbooks")
    st.caption(
        "Every strategy the bot runs — trigger conditions, volume gates, time windows, and what to look for on the chart. "
        "Each entry requires RVOL above its gate, no open position, and the active R:R gate "
        "(1.2 small account / 1.6 professional, balance-based — see Settings) after slippage."
    )
    
    import random as _rng_pb
    
    def _gen_orb_scenario(seed: int, scenario: str) -> dict:
        """
        Generate a synthetic 13-candle ORB session (09:30–11:00 ET, 5-min bars).
        Returns all data needed to render the dual-panel chart.
        scenario: "clean" | "flip" | "rejected"
        """
        r = _rng_pb.Random(seed)
        times = pd.date_range("2026-06-06 09:30", periods=13, freq="5min")
    
        # ── Opening Range candle ──────────────────────────────────────────────
        or_open  = 450.0 + r.uniform(-5, 5)
        or_close = or_open + r.uniform(-0.80, 0.80)
        or_high  = max(or_open, or_close) + r.uniform(0.10, 0.40)
        or_low   = min(or_open, or_close) - r.uniform(0.10, 0.40)
        or_vol   = 1_200_000
    
        bars = [{
            "time":   times[0],
            "open":   or_open,  "high": or_high,
            "low":    or_low,   "close": or_close,
            "volume": or_vol,
        }]
        avg_vol = or_vol * 0.7   # baseline for RVOL = vol / avg
    
        # ── Subsequent candles ────────────────────────────────────────────────
        price = or_close
        for i in range(1, 13):
            if scenario in ("clean", "flip") and i == 3:
                # Breakout candle — strong directional move
                direction_mult = 1 if scenario == "clean" else (-1 if scenario == "flip" else 1)
                b_open  = price
                b_close = price + direction_mult * (or_high - or_low) * r.uniform(1.05, 1.25)
                b_high  = max(b_open, b_close) + r.uniform(0.05, 0.15)
                b_low   = min(b_open, b_close) - r.uniform(0.05, 0.10)
                b_vol   = int(avg_vol * r.uniform(2.3, 3.1))   # RVOL > 200%
            elif scenario == "rejected" and i == 3:
                # Breakout in price but LOW volume (rejected)
                b_open  = price
                b_close = price + (or_high - or_low) * r.uniform(1.05, 1.20)
                b_high  = max(b_open, b_close) + r.uniform(0.05, 0.12)
                b_low   = min(b_open, b_close) - r.uniform(0.05, 0.10)
                b_vol   = int(avg_vol * r.uniform(0.9, 1.4))   # RVOL < 200%
            elif scenario == "clean" and i == 7:
                # Stage-1 target hit — large up candle
                b_open  = price
                b_close = price + r.uniform(0.30, 0.60)
                b_high  = b_close + r.uniform(0.10, 0.20)
                b_low   = b_open  - r.uniform(0.05, 0.10)
                b_vol   = int(avg_vol * r.uniform(1.2, 1.8))
            elif scenario == "flip" and i == 5:
                # First trade stop — sharp reversal
                b_open  = price
                b_close = price - r.uniform(0.40, 0.70)
                b_high  = b_open  + r.uniform(0.05, 0.12)
                b_low   = b_close - r.uniform(0.10, 0.20)
                b_vol   = int(avg_vol * r.uniform(1.5, 2.0))
            elif scenario == "flip" and i == 6:
                # Flip entry candle — breakout of OR low to downside
                b_open  = price
                b_close = price - (or_high - or_low) * r.uniform(1.1, 1.3)
                b_high  = b_open  + r.uniform(0.05, 0.15)
                b_low   = b_close - r.uniform(0.05, 0.10)
                b_vol   = int(avg_vol * r.uniform(2.1, 2.8))   # RVOL > 200%
            else:
                drift   = r.uniform(-0.15, 0.15)
                b_open  = price
                b_close = price + drift
                b_high  = max(b_open, b_close) + r.uniform(0.02, 0.12)
                b_low   = min(b_open, b_close) - r.uniform(0.02, 0.10)
                b_vol   = int(avg_vol * r.uniform(0.6, 1.3))
    
            price = b_close
            bars.append({
                "time": times[i], "open": b_open, "high": b_high,
                "low":  b_low,    "close": b_close, "volume": b_vol,
            })
    
        df = pd.DataFrame(bars)
    
        # VWAP
        df["_tp"]    = (df["high"] + df["low"] + df["close"]) / 3
        df["_tpv"]   = df["_tp"] * df["volume"]
        df["vwap"]   = df["_tpv"].cumsum() / df["volume"].cumsum()
        df["rvol"]   = df["volume"] / avg_vol
    
        # Key price points for annotations
        signal_idx  = 3
        entry_idx   = 4
        if scenario == "clean":
            exit_idx    = 7
            exit_reason = "Stage-1 (+50%)"
        elif scenario == "flip":
            exit_idx    = 5   # first trade stop
            flip_idx    = 6   # flip entry
            flip_exit   = 10  # flip stage-1
        else:
            exit_idx    = 5   # rejected — no entry, show where signal was absent
    
        result = {
            "df":          df,
            "or_high":     or_high,
            "or_low":      or_low,
            "signal_idx":  signal_idx,
            "entry_idx":   entry_idx,
            "avg_vol":     avg_vol,
        }
        if scenario == "flip":
            result.update({"stop_idx": 5, "flip_idx": flip_idx, "flip_exit": flip_exit})
        else:
            result["exit_idx"] = exit_idx
        return result
    
    def _build_orb_fig(d: dict, title: str, scenario: str) -> "go.Figure":
        """
        Combined price + volume chart using make_subplots.
        Row 1 (73%): candlestick + VWAP + ORB shading + A/B/C annotations
        Row 2 (27%): volume bars + 10-day avg + 200% gate
        All text #000000 for readability regardless of theme.
        """
        from plotly.subplots import make_subplots as _msp
        df      = d["df"]
        or_high = d["or_high"]
        or_low  = d["or_low"]
        avol    = d["avg_vol"]
    
        fig = _msp(
            rows=2, cols=1,
            shared_xaxes=True,
            row_heights=[0.73, 0.27],
            vertical_spacing=0.03,
        )
    
        # ── Row 1: ORB shaded range ───────────────────────────────────────────
        fig.add_hrect(y0=or_low, y1=or_high,
                      fillcolor="rgba(255,215,64,0.12)",
                      line_width=1, line_color="rgba(255,215,64,0.4)",
                      annotation_text="Opening Range",
                      annotation_position="right",
                      annotation_font=dict(color="rgba(200,160,0,1)", size=8),
                      row=1, col=1)
        for lvl, lbl, col in [
            (or_high, "OR High", "rgba(0,210,70,0.85)"),
            (or_low,  "OR Low",  "rgba(220,60,60,0.85)"),
        ]:
            fig.add_hline(y=lvl, line_color=col, line_width=1.5, line_dash="dash",
                          annotation_text=lbl, annotation_font_color=col,
                          annotation_position="right", annotation_font_size=9,
                          row=1, col=1)
    
        # ── Row 1: Candlesticks ───────────────────────────────────────────────
        for idx, row in df.iterrows():
            if idx == d["signal_idx"]:
                bc = ("#00c853" if scenario == "clean" else
                      "#ff5252" if scenario == "flip" else "#ffd740")
                alpha = 1.0
            elif scenario == "flip" and idx == d.get("flip_idx"):
                bc, alpha = "#a78bfa", 1.0
            else:
                bc    = "#00e676" if row["close"] >= row["open"] else "#ff5252"
                alpha = 0.75
            fig.add_shape(type="line",
                x0=row["time"], x1=row["time"],
                y0=row["low"],  y1=row["high"],
                line=dict(color=bc, width=1.5), row=1, col=1)
            fig.add_shape(type="rect",
                x0=row["time"] - pd.Timedelta(minutes=2),
                x1=row["time"] + pd.Timedelta(minutes=2),
                y0=min(row["open"], row["close"]),
                y1=max(row["open"], row["close"]),
                fillcolor=bc, opacity=alpha, line_width=0, row=1, col=1)
    
        # ── Row 1: VWAP (bold orange) ─────────────────────────────────────────
        fig.add_trace(go.Scatter(
            x=df["time"], y=df["vwap"],
            mode="lines", name="VWAP",
            line=dict(color="#ff9800", width=2.5),
            hovertemplate="VWAP: $%{y:.2f}<extra></extra>",
        ), row=1, col=1)
    
        # ── Row 1: VWAP cross annotation ──────────────────────────────────────
        for i in range(1, len(df)):
            if (df.iloc[i-1]["close"] > df.iloc[i-1]["vwap"]) != (df.iloc[i]["close"] > df.iloc[i]["vwap"]):
                fig.add_annotation(
                    x=df.iloc[i]["time"], y=df.iloc[i]["close"],
                    text="⚡ VWAP Cross", showarrow=True, arrowhead=2,
                    ax=0, ay=-30, font=dict(color="#ff9800", size=8, family="Arial Black"),
                    arrowcolor="#ff9800", arrowwidth=1.5,
                    row=1, col=1,
                )
                break
    
        # ── Row 1: A/B/C and scenario-specific annotations ───────────────────
        _yd = float(df["high"].max() - df["low"].min()) * 0.08  # dynamic offset
    
        def _marker(idx, label, color, above=True):
            row_d = df.iloc[idx]
            y = row_d["high"] + _yd if above else row_d["low"] - _yd
            ay_v = -30 if above else 30
            fig.add_annotation(
                x=row_d["time"], y=y,
                text=f"<b>{label}</b>",
                showarrow=True, arrowhead=3, ax=0, ay=ay_v,
                font=dict(color=color, size=9, family="Arial Black"),
                arrowcolor=color, arrowwidth=2,
                bgcolor="rgba(255,255,255,0.7)",
                bordercolor=color, borderwidth=1, borderpad=3,
                row=1, col=1,
            )
    
        if scenario == "clean":
            # Stage-1 exit line
            _s1_price = df.iloc[d["entry_idx"]]["close"] * 1.50
            fig.add_hline(y=_s1_price, line_color="rgba(0,200,80,.80)",
                          line_dash="dot", line_width=1.5,
                          annotation_text="Stage-1 target +50%",
                          annotation_font_color="rgba(0,160,70,1)",
                          annotation_font_size=8, annotation_position="right",
                          row=1, col=1)
            # Stop-loss line
            _sl_price = df.iloc[d["entry_idx"]]["close"] * 0.70
            fig.add_hline(y=_sl_price, line_color="rgba(220,60,60,.70)",
                          line_dash="dot", line_width=1.2,
                          annotation_text="Hard stop −30%",
                          annotation_font_color="rgba(180,40,40,1)",
                          annotation_font_size=8, annotation_position="right",
                          row=1, col=1)
            _marker(d["signal_idx"], "A · Signal", "#ffd740")
            _marker(d["entry_idx"],  "B · Entry",  "#00e5ff")
            _marker(d["exit_idx"],   "C · Stage-1 Exit", "#00e676")
            # Stage-2 BE annotation
            fig.add_annotation(
                x=df.iloc[d["exit_idx"]]["time"],
                y=df.iloc[d["entry_idx"]]["close"],
                text="<b>Stage-2: 50% rides<br>to break-even</b>",
                showarrow=True, arrowhead=2,
                ax=40, ay=0,
                font=dict(color="#00bcd4", size=8),
                arrowcolor="#00bcd4", arrowwidth=1.2,
                bgcolor="rgba(255,255,255,0.8)", bordercolor="#00bcd4", borderpad=3,
                row=1, col=1,
            )
    
        elif scenario == "flip":
            _sl_price1 = df.iloc[d["entry_idx"]]["close"] * 0.70
            fig.add_hline(y=_sl_price1, line_color="rgba(220,60,60,.70)",
                          line_dash="dot", line_width=1.2,
                          annotation_text="Stop −30% → Flip Armed",
                          annotation_font_color="rgba(180,40,40,1)",
                          annotation_font_size=8, annotation_position="right",
                          row=1, col=1)
            _marker(d["signal_idx"], "A · Signal",   "#ffd740")
            _marker(d["entry_idx"],  "B · Entry",    "#00e5ff")
            _marker(d["stop_idx"],   "✗ Stop-Loss",  "#ff5252")
            _marker(d["flip_idx"],   "⚡ Flip Entry", "#a78bfa", above=False)
            _fe = min(d["flip_exit"], len(df)-1)
            _marker(_fe, "C · Flip Exit", "#00e676")
            fig.add_annotation(
                x=df.iloc[d["flip_idx"]]["time"],
                y=df.iloc[d["flip_idx"]]["high"] + _yd * 2.5,
                text="<b>Flip armed instantly<br>on 30% hard stop</b>",
                showarrow=False,
                font=dict(color="#a78bfa", size=8),
                bgcolor="rgba(255,255,255,0.85)", bordercolor="#a78bfa", borderpad=3,
                row=1, col=1,
            )
    
        elif scenario == "rejected":
            _marker(d["signal_idx"], "A · Price ✓", "#ffd740")
            fig.add_annotation(
                x=df.iloc[d["signal_idx"]]["time"],
                y=df.iloc[d["signal_idx"]]["low"] - _yd * 2.5,
                text="<b>❌ RVOL < 200%<br>NO ENTRY — volume gate failed</b>",
                showarrow=True, arrowhead=2,
                ax=0, ay=28,
                font=dict(color="#ff5252", size=9, family="Arial Black"),
                arrowcolor="#ff5252", arrowwidth=1.5,
                bgcolor="rgba(255,255,255,0.9)", bordercolor="#ff5252", borderpad=4,
                row=1, col=1,
            )
            # Show where a phantom entry would have stopped out
            fig.add_annotation(
                x=df.iloc[min(d["signal_idx"]+2, len(df)-1)]["time"],
                y=df.iloc[d["signal_idx"]]["close"] * 0.97,
                text="Without volume → immediate reversal",
                showarrow=False,
                font=dict(color="#888", size=7),
                row=1, col=1,
            )
    
        # ── Row 2: Volume bars ────────────────────────────────────────────────
        vol_colors = []
        for idx, row in df.iterrows():
            if idx == d["signal_idx"]:
                col = ("#00c853" if scenario == "clean" else
                       "#ff5252" if scenario == "flip" else "#ffd740")
            elif scenario == "flip" and idx == d.get("flip_idx"):
                col = "#a78bfa"
            else:
                col = ("rgba(0,229,255,0.45)" if row["close"] >= row["open"]
                       else "rgba(255,82,82,0.45)")
            vol_colors.append(col)
    
        fig.add_trace(go.Bar(
            x=df["time"], y=df["volume"],
            marker_color=vol_colors, marker_line_width=0,
            hovertemplate="%{x|%H:%M}<br>Vol: %{y:,.0f}<extra></extra>",
        ), row=2, col=1)
        # 10-day avg line
        fig.add_hline(y=avol, line_color="rgba(255,152,0,0.7)", line_dash="dot",
                      line_width=1.5, annotation_text="10-day avg",
                      annotation_font_color="rgba(200,120,0,0.9)",
                      annotation_font_size=8, annotation_position="right",
                      row=2, col=1)
        # 200% gate
        fig.add_hline(y=avol * 2.0, line_color="rgba(0,200,100,0.8)", line_dash="dot",
                      line_width=2, annotation_text="200% gate",
                      annotation_font_color="rgba(0,160,80,1)",
                      annotation_font_size=9, annotation_position="right",
                      row=2, col=1)
    
        # ── Layout ────────────────────────────────────────────────────────────
        fig.update_layout(
            title=dict(text=title, font=dict(size=12, color="#000000", family="Arial Black"), x=0.01),
            template="plotly_white",
            paper_bgcolor=T["plot_paper"], plot_bgcolor=T["plot_bg"],
            height=440,
            margin=dict(l=8, r=110, t=38, b=8),
            font=dict(color="#000000", size=8),
            showlegend=False,
            hovermode="x unified",
            bargap=0.06,
        )
        fig.update_xaxes(type="date", tickformat="%H:%M",
                         tickfont=dict(color="#000000", size=7),
                         gridcolor="rgba(0,0,0,0.08)",
                         showticklabels=False, row=1, col=1)
        fig.update_xaxes(type="date", tickformat="%H:%M",
                         tickfont=dict(color="#000000", size=7),
                         gridcolor="rgba(0,0,0,0.08)",
                         showticklabels=True, row=2, col=1)
        fig.update_yaxes(tickprefix="$", tickfont=dict(color="#000000", size=7),
                         gridcolor="rgba(0,0,0,0.08)", row=1, col=1)
        fig.update_yaxes(tickformat=".2s", tickfont=dict(color="#000000", size=6),
                         gridcolor="rgba(0,0,0,0.08)", row=2, col=1)
        return fig
    
    def _build_volume_fig(d: dict, scenario: str, rvol_threshold: float = 2.0) -> "go.Figure":
        """DEPRECATED — volume is now combined into _build_orb_fig. Kept as no-op."""
        return go.Figure()   # returns empty so existing calls don't break
    
    def _build_strategy_fig(strategy: str, seed: int = 42) -> "go.Figure":
        """
        Synthetic dual-panel chart (price + volume) for strategies 2–8.
        strategy: "bos_mss"|"vwap_pb"|"fvg"|"mid_brk"|"aft_rev"|"trend_cont"|"chan_break"
        Visual style matches _build_orb_fig (plotly_white, #000 text, same palette).
        """
        from plotly.subplots import make_subplots as _msp
        r = _rng_pb.Random(seed)
        n = {"bos_mss":22,"vwap_pb":20,"fvg":22,"mid_brk":24,
             "aft_rev":30,"trend_cont":20,"chan_break":25}.get(strategy, 20)
        base     = 450.0 + r.uniform(-15, 15)
        avg_vol  = 900_000
    
        bars = []
    
        def _b(p, od=0.0, cd=0.0, wh=0.12, wl=0.10, vm=1.0):
            """One synthetic OHLCV bar centred near price p."""
            _o = p + od;  _c = p + cd
            return {"open":_o,"high":max(_o,_c)+wh,"low":min(_o,_c)-wl,
                    "close":_c,"volume":int(avg_vol*vm*r.uniform(0.8,1.2))}
    
        price       = base
        signal_idx  = None
        entry_idx   = None
        exit_idx    = None
        annotations = []   # {idx, label, color, above}
        hlines      = []   # (y, color, dash, label)
        hrects      = []   # {y0, y1, fillcolor, line_color, label}
        channel_pts = []   # (idx, y) for chan_break trendline
    
        # ── BOS_MSS ──────────────────────────────────────────────────────────
        if strategy == "bos_mss":
            sl_y = None
            for i in range(n):
                if   i == 0:  b = _b(price,-0.10, 0.35, 0.20, 0.12)
                elif i == 1:  b = _b(price, 0.30,-0.45, 0.15, 0.20)
                elif i == 2:  b = _b(price,-0.40,-0.50, 0.10, 0.20)
                elif i == 3:  b = _b(price,-0.45,-0.35, 0.12, 0.18); sl_y = price - 0.35 - 0.18
                elif i == 4:  b = _b(price,-0.30, 0.40, 0.15, 0.10)
                elif i == 5:  b = _b(price, 0.35, 0.25, 0.18, 0.12)
                elif i == 6:  b = _b(price, 0.20,-0.30, 0.12, 0.18)
                elif i == 7:  b = _b(price,-0.25,-0.40, 0.10, 0.20)
                elif i == 8:  b = _b(price,-0.35,-0.20, 0.12, 0.16)
                elif i == 9:  b = _b(price,-0.20, 0.15, 0.14, 0.12)
                elif i == 10: b = _b(price, 0.10,-0.10, 0.12, 0.10)
                elif i == 11:
                    b = _b(price,-0.15,-0.60, 0.08, 0.22, vm=2.4)
                    signal_idx = i
                elif i == 12:
                    b = _b(price,-0.55,-0.45, 0.10, 0.20, vm=1.8)
                    entry_idx = i
                else:         b = _b(price,-0.10,-0.30+r.uniform(-0.10,0.05), 0.10, 0.18)
                price = b["close"]; bars.append(b)
            if sl_y:
                hlines.append((sl_y,"rgba(255,82,82,0.8)","dash","Prior SL (BOS level)"))
            annotations += [
                {"idx":0,  "label":"SH",          "color":"#ff9800","above":True},
                {"idx":5,  "label":"LH",          "color":"#ff9800","above":True},
                {"idx":3,  "label":"SL",          "color":"#ff5252","above":False},
                {"idx":11, "label":"A · Signal",  "color":"#ffd740","above":True},
                {"idx":12, "label":"B · Entry",   "color":"#00e5ff","above":False},
            ]
    
        # ── VWAP_PB ──────────────────────────────────────────────────────────
        elif strategy == "vwap_pb":
            for i in range(n):
                if   i <  6: b = _b(price, r.uniform(-0.05,0.10), r.uniform(0.20,0.45), 0.12, 0.08)
                elif i <= 8: b = _b(price, r.uniform(0.05,0.12),  r.uniform(-0.18,-0.08),0.10, 0.16)
                elif i == 9:
                    b = _b(price, r.uniform(-0.05,0.05), r.uniform(0.15,0.30), 0.08, 0.22, vm=1.9)
                    signal_idx = i
                elif i == 10:
                    b = _b(price, r.uniform(0.00,0.08),  r.uniform(0.20,0.35), 0.12, 0.08, vm=1.5)
                    entry_idx = i
                elif i == 15:
                    b = _b(price, r.uniform(0.05,0.12),  r.uniform(0.25,0.40), 0.15, 0.08, vm=1.3)
                    exit_idx = i
                else:        b = _b(price, r.uniform(-0.05,0.10), r.uniform(0.10,0.30), 0.12, 0.08)
                price = b["close"]; bars.append(b)
            annotations += [
                {"idx":signal_idx or 9,  "label":"A · VWAP Touch",   "color":"#ffd740","above":False},
                {"idx":entry_idx  or 10, "label":"B · Entry",        "color":"#00e5ff","above":True},
                {"idx":exit_idx   or 15, "label":"C · Stage-1 Exit", "color":"#00e676","above":True},
            ]
    
        # ── FVG ──────────────────────────────────────────────────────────────
        elif strategy == "fvg":
            fvg_top = fvg_bot = None
            for i in range(n):
                if   i <  4: b = _b(price, r.uniform(-0.05,0.08), r.uniform(0.15,0.30), 0.12, 0.08)
                elif i == 4:
                    b = _b(price, r.uniform(-0.05,0.10), r.uniform(0.10,0.20), 0.12, 0.08)
                    fvg_top = price + 0.10 - 0.12   # bar4 low ≈ bottom of up-candle body
                elif i == 5:
                    b = _b(price, r.uniform(0.05,0.15), -r.uniform(1.0,1.4), 0.08, 0.25, vm=3.0)
                elif i == 6:
                    b = _b(price, r.uniform(-0.10,0.00), r.uniform(-0.25,-0.10), 0.08, 0.18)
                    fvg_bot = price - 0.10 + 0.08   # bar6 high ≈ top of down-candle body
                elif i <  10: b = _b(price, r.uniform(-0.12,0.00), r.uniform(-0.20,-0.05), 0.10, 0.16)
                elif i == 10: b = _b(price, r.uniform(-0.10,0.00), r.uniform(0.15,0.30), 0.12, 0.10)
                elif i <  14: b = _b(price, r.uniform(-0.05,0.08), r.uniform(0.10,0.25), 0.12, 0.08)
                elif i == 14:
                    b = _b(price, r.uniform(0.00,0.08), r.uniform(0.05,0.15), 0.10, 0.10, vm=1.8)
                    signal_idx = i
                elif i == 15:
                    b = _b(price, r.uniform(0.00,0.08), r.uniform(-0.20,-0.08), 0.14, 0.12, vm=1.5)
                    entry_idx = i
                else:        b = _b(price, r.uniform(-0.08,0.05), r.uniform(-0.25,-0.05), 0.12, 0.18)
                price = b["close"]; bars.append(b)
            if fvg_top and fvg_bot:
                y0, y1 = sorted([fvg_top, fvg_bot])
                hrects.append({"y0":y0,"y1":y1,
                                "fillcolor":"rgba(255,152,0,0.14)",
                                "line_color":"rgba(255,152,0,0.4)","label":"FVG Zone"})
            annotations += [
                {"idx":5,  "label":"⚡ Impulse",      "color":"#ff5252","above":True},
                {"idx":signal_idx or 14,"label":"A · Gap Fill","color":"#ffd740","above":True},
                {"idx":entry_idx  or 15,"label":"B · Entry PUT","color":"#00e5ff","above":False},
            ]
    
        # ── MID_BRK ──────────────────────────────────────────────────────────
        elif strategy == "mid_brk":
            or_low_y = None
            for i in range(n):
                if   i == 0:
                    b = _b(price,-0.10, 0.40, 0.20, 0.12)
                    or_low_y = price - 0.12
                elif i <  4:  b = _b(price, r.uniform(0.05,0.12),  r.uniform(-0.10,0.20), 0.14, 0.12)
                elif i == 4:  b = _b(price, r.uniform(0.05,0.10),  r.uniform(-0.20,-0.05),0.10, 0.16)
                elif i <  8:  b = _b(price, r.uniform(-0.05,0.08), r.uniform(-0.12,0.05), 0.10, 0.14)
                elif i <  12: b = _b(price, r.uniform(-0.05,0.05), r.uniform(-0.08,0.08), 0.08, 0.10)
                elif i == 12:
                    b = _b(price, r.uniform(-0.08,0.02), -r.uniform(0.50,0.70), 0.08, 0.22, vm=2.5)
                    signal_idx = i
                elif i == 13:
                    b = _b(price,-r.uniform(0.05,0.15),-r.uniform(0.25,0.40), 0.10, 0.18, vm=1.8)
                    entry_idx = i
                else:        b = _b(price, r.uniform(-0.12,0.00), r.uniform(-0.30,-0.05), 0.10, 0.20)
                price = b["close"]; bars.append(b)
            if or_low_y:
                hlines.append((or_low_y,"rgba(255,82,82,0.8)","dash","OR Low"))
            annotations += [
                {"idx":4,            "label":"LH",            "color":"#ff9800","above":True},
                {"idx":signal_idx or 12,"label":"A · Breakdown","color":"#ffd740","above":True},
                {"idx":entry_idx  or 13,"label":"B · Entry PUT","color":"#00e5ff","above":False},
            ]
    
        # ── AFT_REV ──────────────────────────────────────────────────────────
        elif strategy == "aft_rev":
            lh_y = None
            for i in range(n):
                if   i == 0: b = _b(price,-0.10, 0.40, 0.22, 0.12)
                elif i <  5: b = _b(price, r.uniform(0.05,0.12),  r.uniform(-0.20,-0.05),0.12, 0.18)
                elif i == 5:
                    b = _b(price, r.uniform(0.05,0.10), r.uniform(0.15,0.30), 0.14, 0.10)
                    lh_y = price + 0.30 + 0.14
                elif i <  9: b = _b(price, r.uniform(-0.05,0.08), r.uniform(-0.15,0.00), 0.10, 0.14)
                elif i == 9:
                    b = _b(price, r.uniform(0.05,0.10), r.uniform(0.20,0.35), 0.16, 0.10)
                elif i < 14: b = _b(price, r.uniform(-0.05,0.08), r.uniform(-0.20,-0.05),0.10, 0.16)
                elif i < 17: b = _b(price, r.uniform(-0.08,0.05), r.uniform(-0.05,0.15), 0.10, 0.08)
                elif i == 17:
                    b = _b(price, r.uniform(-0.05,0.05), r.uniform(0.25,0.40), 0.14, 0.08, vm=2.0)
                    signal_idx = i
                elif i == 18:
                    b = _b(price, r.uniform(0.00,0.08), r.uniform(0.20,0.35), 0.12, 0.08, vm=1.7)
                    entry_idx = i
                else:        b = _b(price, r.uniform(0.00,0.10), r.uniform(0.10,0.30), 0.14, 0.08)
                price = b["close"]; bars.append(b)
            if lh_y:
                hlines.append((lh_y,"rgba(255,152,0,0.8)","dash","Prior LH (BOS level)"))
            annotations += [
                {"idx":5,  "label":"LH",             "color":"#ff9800","above":True},
                {"idx":9,  "label":"LH",             "color":"#ff9800","above":True},
                {"idx":14, "label":"HL",             "color":"#00e676","above":False},
                {"idx":signal_idx or 17,"label":"A · BOS Signal", "color":"#ffd740","above":True},
                {"idx":entry_idx  or 18,"label":"B · Entry CALL","color":"#00e5ff","above":False},
            ]
    
        # ── TREND_CONT ────────────────────────────────────────────────────────
        elif strategy == "trend_cont":
            lh_close = None
            for i in range(n):
                if   i <  4:
                    b = _b(price, r.uniform(0.05,0.12), r.uniform(-0.30,-0.15), 0.10, 0.22)
                elif i == 4: b = _b(price, r.uniform(-0.15,-0.05), r.uniform(0.20,0.35), 0.16, 0.08)
                elif i == 5: b = _b(price, r.uniform(-0.05,0.05),  r.uniform(0.15,0.25), 0.14, 0.08)
                elif i == 6: b = _b(price, r.uniform(0.00,0.08),   r.uniform(0.05,0.15), 0.12, 0.08)
                elif i == 7:
                    b = _b(price, r.uniform(0.00,0.05), r.uniform(-0.05,0.08), 0.12, 0.10)
                    lh_close = price + r.uniform(-0.05, 0.08)
                elif i == 8: b = _b(price, r.uniform(-0.05,0.05), r.uniform(-0.10,0.05), 0.10, 0.10)
                elif i == 9:
                    drop = max(0.05, (lh_close or price) - price + r.uniform(0.02, 0.10))
                    b = _b(price, r.uniform(-0.08,0.00), -drop, 0.08, 0.16, vm=1.8)
                    signal_idx = i
                elif i == 10:
                    b = _b(price, r.uniform(-0.10,0.00), r.uniform(-0.25,-0.10), 0.10, 0.18, vm=1.5)
                    entry_idx = i
                else:        b = _b(price, r.uniform(-0.05,0.05), r.uniform(-0.25,-0.05), 0.10, 0.18)
                price = b["close"]; bars.append(b)
            if lh_close:
                hlines.append((lh_close,"rgba(255,152,0,0.8)","dash","LH bar close (re-entry gate)"))
            annotations += [
                {"idx":7,            "label":"LH · Resistance",  "color":"#ff9800","above":True},
                {"idx":signal_idx or 9, "label":"A · Rejection", "color":"#ffd740","above":False},
                {"idx":entry_idx or 10, "label":"B · Re-entry PUT","color":"#00e5ff","above":False},
            ]
    
        # ── CHAN_BREAK ────────────────────────────────────────────────────────
        else:
            sh_pts = []   # (idx, high_y) for descending trendline
            for i in range(n):
                if   i == 0: b = _b(price,-0.10, 0.50, 0.25, 0.12)
                elif i <  3: b = _b(price, r.uniform(0.05,0.12), r.uniform(-0.20,-0.05),0.10, 0.18)
                elif i == 3:
                    b = _b(price, r.uniform(0.05,0.10), r.uniform(0.20,0.35), 0.18, 0.10)
                    sh_pts.append((3, price + 0.35 + 0.18))
                elif i <  7: b = _b(price, r.uniform(-0.05,0.08), r.uniform(-0.20,-0.05),0.10, 0.18)
                elif i == 7:
                    b = _b(price, r.uniform(-0.08,0.05), r.uniform(0.15,0.28), 0.18, 0.10)
                    sh_pts.append((7, price + 0.28 + 0.18))
                elif i < 12: b = _b(price, r.uniform(-0.05,0.08), r.uniform(-0.20,-0.05),0.10, 0.18)
                elif i == 12:
                    b = _b(price, r.uniform(-0.08,0.05), r.uniform(0.10,0.22), 0.16, 0.10)
                    sh_pts.append((12, price + 0.22 + 0.16))
                elif i < 17: b = _b(price, r.uniform(-0.05,0.08), r.uniform(-0.18,-0.05),0.10, 0.16)
                elif i == 17:
                    if len(sh_pts) >= 2:
                        x1,y1 = sh_pts[-2]; x2,y2 = sh_pts[-1]
                        slope  = (y2-y1)/(x2-x1) if x2!=x1 else 0
                        proj_y = y2 + slope*(17-x2)
                        b = {"open":  price+r.uniform(0.00,0.05),
                             "high":  proj_y+r.uniform(0.02,0.06),
                             "close": proj_y-r.uniform(0.08,0.14),
                             "volume":int(avg_vol*r.uniform(1.6,2.2))}
                        b["low"] = b["close"]-r.uniform(0.05,0.10)
                        channel_pts = sh_pts[:]
                    else:
                        b = _b(price, r.uniform(-0.08,0.00), r.uniform(-0.15,-0.05),0.16,0.12,vm=1.8)
                    signal_idx = i
                elif i == 18:
                    b = _b(price, r.uniform(-0.10,0.00), r.uniform(-0.20,-0.05),0.10,0.18,vm=1.5)
                    entry_idx = i
                else: b = _b(price, r.uniform(-0.05,0.05), r.uniform(-0.20,-0.05),0.10,0.16)
                price = b["close"]; bars.append(b)
            annotations += [
                {"idx":3,  "label":"SH 1",        "color":"#ff9800","above":True},
                {"idx":7,  "label":"SH 2",        "color":"#ff9800","above":True},
                {"idx":12, "label":"SH 3",        "color":"#ff9800","above":True},
                {"idx":signal_idx or 17,"label":"A · Rejection","color":"#ffd740","above":True},
                {"idx":entry_idx  or 18,"label":"B · Entry PUT","color":"#00e5ff","above":False},
            ]
    
        # ── Build DataFrame ───────────────────────────────────────────────────
        times = pd.date_range("2026-06-06 09:30", periods=n, freq="5min")
        df = pd.DataFrame(bars)
        df["time"]  = times[:len(df)]
        df["_tp"]   = (df["high"]+df["low"]+df["close"])/3
        df["_tpv"]  = df["_tp"]*df["volume"]
        df["vwap"]  = df["_tpv"].cumsum()/df["volume"].cumsum()
    
        # ── Figure ────────────────────────────────────────────────────────────
        fig = _msp(rows=2, cols=1, shared_xaxes=True,
                   row_heights=[0.73,0.27], vertical_spacing=0.03)
    
        # Horizontal rect bands (FVG zone etc.)
        for hr in hrects:
            fig.add_hrect(y0=hr["y0"], y1=hr["y1"],
                          fillcolor=hr["fillcolor"],
                          line_width=1, line_color=hr["line_color"],
                          annotation_text=hr.get("label",""),
                          annotation_position="right",
                          annotation_font=dict(color="rgba(200,120,0,1)",size=8),
                          row=1, col=1)
    
        # Horizontal lines (key levels)
        for hy, hc, hd, hl in hlines:
            fig.add_hline(y=hy, line_color=hc, line_dash=hd, line_width=1.5,
                          annotation_text=hl, annotation_font_color=hc,
                          annotation_position="right", annotation_font_size=9,
                          row=1, col=1)
    
        # Candlesticks
        _dy = float(df["high"].max()-df["low"].min())*0.07
        for idx, row in df.iterrows():
            if idx == signal_idx:
                bc = "#ffd740"; alpha = 1.0
            elif idx == entry_idx:
                bc = "#00e5ff"; alpha = 1.0
            else:
                bc    = "#00e676" if row["close"] >= row["open"] else "#ff5252"
                alpha = 0.75
            fig.add_shape(type="line",
                          x0=row["time"],x1=row["time"],y0=row["low"],y1=row["high"],
                          line=dict(color=bc,width=1.5),row=1,col=1)
            fig.add_shape(type="rect",
                          x0=row["time"]-pd.Timedelta(minutes=2),
                          x1=row["time"]+pd.Timedelta(minutes=2),
                          y0=min(row["open"],row["close"]),
                          y1=max(row["open"],row["close"]),
                          fillcolor=bc,opacity=alpha,line_width=0,row=1,col=1)
    
        # VWAP
        fig.add_trace(go.Scatter(
            x=df["time"],y=df["vwap"],mode="lines",name="VWAP",
            line=dict(color="#ff9800",width=2.0),
            hovertemplate="VWAP: $%{y:.2f}<extra></extra>",
        ), row=1, col=1)
    
        # Descending channel trendline (chan_break only)
        if channel_pts and len(channel_pts) >= 2:
            x1i,y1v = channel_pts[0]; x2i,y2v = channel_pts[-1]
            slope = (y2v-y1v)/(x2i-x1i) if x2i!=x1i else 0
            t_ext = [df["time"].iloc[max(0,x1i-1)], df["time"].iloc[min(n-1,x2i+7)]]
            y_ext = [y1v+slope*(max(0,x1i-1)-x1i), y1v+slope*(min(n-1,x2i+7)-x1i)]
            fig.add_trace(go.Scatter(
                x=t_ext, y=y_ext, mode="lines", name="Channel",
                line=dict(color="rgba(255,152,0,0.9)",width=2,dash="dash"),
                hoverinfo="skip",
            ), row=1, col=1)
    
        # Annotations
        for ann in annotations:
            ai = ann["idx"]
            if ai >= len(df): continue
            row_d = df.iloc[ai]
            yp  = row_d["high"]+_dy if ann["above"] else row_d["low"]-_dy
            ayv = -28 if ann["above"] else 28
            fig.add_annotation(
                x=row_d["time"], y=yp,
                text=f"<b>{ann['label']}</b>",
                showarrow=True,arrowhead=3,ax=0,ay=ayv,
                font=dict(color=ann["color"],size=9,family="Arial Black"),
                arrowcolor=ann["color"],arrowwidth=2,
                bgcolor="rgba(255,255,255,0.75)",
                bordercolor=ann["color"],borderwidth=1,borderpad=3,
                row=1, col=1,
            )
    
        # Volume bars
        vol_colors = []
        for idx, row in df.iterrows():
            if   idx == signal_idx: vc = "#ffd740"
            elif idx == entry_idx:  vc = "#00e5ff"
            else: vc = "rgba(0,229,255,0.45)" if row["close"]>=row["open"] else "rgba(255,82,82,0.45)"
            vol_colors.append(vc)
        fig.add_trace(go.Bar(x=df["time"],y=df["volume"],
                             marker_color=vol_colors,marker_line_width=0,
                             hovertemplate="%{x|%H:%M}<br>Vol:%{y:,.0f}<extra></extra>"),
                      row=2, col=1)
        fig.add_hline(y=avg_vol,      line_color="rgba(255,152,0,0.7)",line_dash="dot",line_width=1.5,
                      annotation_text="avg",annotation_font_color="rgba(200,120,0,0.9)",
                      annotation_font_size=8,annotation_position="right",row=2,col=1)
        fig.add_hline(y=avg_vol*1.5,  line_color="rgba(0,200,100,0.8)",line_dash="dot",line_width=1.8,
                      annotation_text="150% gate",annotation_font_color="rgba(0,160,80,1)",
                      annotation_font_size=9,annotation_position="right",row=2,col=1)
    
        # Layout
        _titles = {
            "bos_mss":    "BOS_MSS — Break of Structure  |  PUT fires after SL break · RVOL ≥ 150%",
            "vwap_pb":    "VWAP_PB — VWAP Pullback  |  HL touch + close above VWAP · RVOL ≥ 150%",
            "fvg":        "FVG — Fair Value Gap  |  Price returns to fill 3-bar imbalance zone",
            "mid_brk":    "MID_BRK — Midday Breakdown  |  OR Low breaks 11:00–13:30 · LH confirmed",
            "aft_rev":    "AFT_REV — Afternoon Reversal  |  HL forms → BOS above LH · CALL",
            "trend_cont": "TREND_CONT — Trend Continuation  |  LH re-entry on pullback failure · PUT",
            "chan_break":  "CHAN_BREAK — Channel Rejection  |  Wick tags descending line · body rejects",
        }
        fig.update_layout(
            title=dict(text=_titles.get(strategy, strategy),
                       font=dict(size=11,color="#000000",family="Arial Black"),x=0.01),
            template="plotly_white",
            paper_bgcolor=T["plot_paper"],plot_bgcolor=T["plot_bg"],
            height=420,margin=dict(l=8,r=120,t=38,b=8),
            font=dict(color="#000000",size=8),
            showlegend=False,hovermode="x unified",bargap=0.06,
        )
        fig.update_xaxes(type="date",tickformat="%H:%M",tickfont=dict(color="#000000",size=7),
                         gridcolor="rgba(0,0,0,0.08)",showticklabels=False,row=1,col=1)
        fig.update_xaxes(type="date",tickformat="%H:%M",tickfont=dict(color="#000000",size=7),
                         gridcolor="rgba(0,0,0,0.08)",showticklabels=True,row=2,col=1)
        fig.update_yaxes(tickprefix="$",tickfont=dict(color="#000000",size=7),
                         gridcolor="rgba(0,0,0,0.08)",row=1,col=1)
        fig.update_yaxes(tickformat=".2s",tickfont=dict(color="#000000",size=6),
                         gridcolor="rgba(0,0,0,0.08)",row=2,col=1)
        return fig
    
    
    # ── Per-scenario P&L math (balance-aware) ────────────────────────────────
    from config import get_risk_tier as _pb_get_tier, get_settings as _pb_settings
    _pb_bal      = float(_pb_settings().get("last_known_balance", 5_000.0) or 5_000.0)
    _pb_risk_pct = _pb_get_tier(_pb_bal)
    _pb_risk_usd = _pb_bal * _pb_risk_pct
    _pb_contracts = max(1, int(_pb_risk_usd // 50))   # assume $0.50 avg premium = $50/contract
    _pb_s1_profit = _pb_risk_usd * 0.50 * 0.50        # +50% on 50% of position at Stage-1
    _pb_max_loss  = _pb_risk_usd                       # 30% hard stop → full risk budget gone
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
        f" &nbsp;·&nbsp; Risk/trade: <b>${_pb_risk_usd:,.0f}</b>"
        f" &nbsp;·&nbsp; ~{_pb_contracts} contract(s) at $0.50 premium"
        f" &nbsp;·&nbsp; Stage-1 profit: <b>+${_pb_s1_profit:,.0f}</b>"
        f" &nbsp;·&nbsp; Max loss: <b>−${_pb_max_loss:,.0f}</b>"
        f"</div>",
        unsafe_allow_html=True,
    )
    
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
    
    # ── Tab 1: INST_ORB ───────────────────────────────────────────────────────
    with _pb_tabs[0]:
        st.markdown("**INST_ORB — Institutional Opening Range Breakout**")
        st.markdown(
            "The opening range (OR) is the first 5-minute candle. "
            "When price closes convincingly above OR High with 2× normal volume and price is above VWAP, "
            "institutions are buying the breakout. Below OR Low with same criteria = PUT. "
            "This is the highest-confidence setup — fires earliest in the session."
        )
        _strat_card([
            ("Trigger",          "Close above OR High (CALL) · close below OR Low (PUT)"),
            ("Time Window",      "09:31 – 10:30 ET · first hour only"),
            ("Volume Gate",      "RVOL ≥ 200% — double normal participation required"),
            ("VWAP Gate",        "Price must be above VWAP for CALL · below VWAP for PUT"),
            ("Confidence Range", "0.75 – 0.93 (highest of all 8 strategies)"),
            ("Exit Rules",       "Stage-1: +50% profit → sell 50% · Stage-2: break-even stop · Time-box: 45 min"),
            ("Flip Trigger",     "Hard stop only → arms immediate opposite-direction entry if RVOL still ≥ 200%"),
            ("What to watch",    "Gold/breakout candle clears OR boundary · volume bar crosses green 200% gate line"),
        ], color="#f59e0b")
        _d0 = _gen_orb_scenario(seed=101, scenario="clean")
        st.plotly_chart(
            _build_orb_fig(_d0, "INST_ORB — Clean Breakout  |  RVOL 2.4× · R:R ≥ 1.6", "clean"),
            use_container_width=True,
        )
        st.info(
            "A = signal candle · B = entry (next bar open) · C = Stage-1 exit (+50% on option). "
            "If the volume bar is below the green gate line at A, the bot does not enter — no exceptions."
        )
    
        # Flip example
        st.markdown("---")
        st.markdown("**Flip Trade — same strategy, direction reverses after hard stop**")
        st.markdown(
            "When a hard 30% stop fires, the bot immediately checks whether the opposite OR extreme is breaking "
            "with RVOL ≥ 200%. If yes, it re-enters in the opposite direction. No cooldown. Same risk rules apply."
        )
        _d1 = _gen_orb_scenario(seed=202, scenario="flip")
        st.plotly_chart(
            _build_orb_fig(_d1, "INST_ORB — Flip Trade  |  Stop → Instant Reversal", "flip"),
            use_container_width=True,
        )
        st.info("Purple candle = flip entry. ⚡ marker = moment bot pivoted. Identical gates applied to the flip.")
    
        # Rejected example
        st.markdown("---")
        st.markdown("**Rejected Setup — price breaks out, volume does not confirm**")
        _d2 = _gen_orb_scenario(seed=303, scenario="rejected")
        st.plotly_chart(
            _build_orb_fig(_d2, "INST_ORB — Rejected  |  Price ✓  RVOL ✗", "rejected"),
            use_container_width=True,
        )
        st.warning(
            "Volume bar stays below the 200% gate. Price broke OR High but smart money wasn't in it. "
            "This is the classic retail trap — the bot walks away and saves capital."
        )
    
    # ── Tab 2: BOS_MSS ────────────────────────────────────────────────────────
    with _pb_tabs[1]:
        st.markdown("**BOS_MSS — Break of Structure / Market Structure Shift**")
        st.markdown(
            "Price has been making Lower Highs and Lower Lows (downtrend) or Higher Highs and Higher Lows (uptrend). "
            "A Break of Structure (BOS) happens when price takes out the most recent swing low in a downtrend — "
            "confirming the move. A Market Structure Shift (MSS) is the first BOS after a period of consolidation, "
            "signaling a new directional leg is beginning. This is the second-highest confidence setup."
        )
        _strat_card([
            ("Trigger",          "Close breaks prior swing low (PUT) · prior swing high (CALL) with momentum candle"),
            ("Time Window",      "09:45 – 14:30 ET"),
            ("Volume Gate",      "RVOL ≥ 150% at the break candle"),
            ("Trend Context",    "MSA must confirm: at least 1 confirmed Lower High before PUT entry"),
            ("Confidence Range", "0.68 – 0.85"),
            ("Chart DNA",        "Look for: SL annotation on chart → price consolidates → sharp BOS candle breaks below SL"),
            ("Common Mistake",   "Entering on the LL label itself — the entry is when price BREAKS below that level, not at it"),
            ("What to watch",    "Bot labels SH/SL pivots on chart. Entry fires 1 bar after the break closes."),
        ], color="#818cf8")
        st.plotly_chart(
            _build_strategy_fig("bos_mss", seed=42),
            use_container_width=True,
        )
        st.info(
            "**Reading the chart:** When you see SH → LH → SL → LL annotations descending in a stair-step, "
            "the bot is tracking a confirmed downtrend. The PUT fires the bar after price closes below the last SL. "
            "The LL label is an observation — NOT the entry trigger."
        )
    
    # ── Tab 3: VWAP_PB ───────────────────────────────────────────────────────
    with _pb_tabs[2]:
        st.markdown("**VWAP_PB — VWAP Pullback**")
        st.markdown(
            "VWAP (Volume Weighted Average Price) is the average price paid all day, weighted by volume. "
            "Institutions use it as a benchmark — buying below it, selling above it. "
            "In an uptrend, when price dips back to VWAP and forms a Higher Low (HL), that's an institutional "
            "buy zone. The bot enters as price bounces off VWAP with volume. In a downtrend, the inverse applies."
        )
        _strat_card([
            ("Trigger",          "Price touches VWAP from above (uptrend) or below (downtrend) and closes back in trend direction"),
            ("Time Window",      "09:45 – 14:30 ET"),
            ("Volume Gate",      "RVOL ≥ 150% on the bounce candle"),
            ("Trend Context",    "MSA must confirm uptrend (HL pattern) for CALL · downtrend (LH pattern) for PUT"),
            ("Confidence Range", "0.62 – 0.80"),
            ("Chart DNA",        "Price 'kisses' VWAP (orange line), dips barely through, closes back above — that's the signal"),
            ("What to watch",    "The bounce candle must close beyond VWAP in trend direction · volume bar above 150% gate"),
            ("Pro tip",          "Best setups occur when price has been trending for 30+ min and this is the second VWAP test"),
        ], color="#06b6d4")
        st.plotly_chart(
            _build_strategy_fig("vwap_pb", seed=43),
            use_container_width=True,
        )
        st.info(
            "**VWAP is the blue/orange line on the chart.** A clean pullback looks like: "
            "price goes up → pulls back to touch VWAP → bounces with volume. "
            "If price closes through VWAP on the touch candle (not just wicked), the setup fails — the bot skips it."
        )
    
    # ── Tab 4: FVG ────────────────────────────────────────────────────────────
    with _pb_tabs[3]:
        st.markdown("**FVG — Fair Value Gap**")
        st.markdown(
            "A Fair Value Gap is a 3-candle imbalance: candle 1 high, big gap candle 2 (body), candle 3 low. "
            "When candle 3's low is above candle 1's high, the zone between them was never properly traded — "
            "it's a magnet for price. When price returns to fill the gap, institutions who missed the move "
            "are waiting there. The bot enters as price enters the gap zone with volume."
        )
        _strat_card([
            ("Trigger",          "Price re-enters a prior 3-bar imbalance zone (gap between candle 1 high and candle 3 low)"),
            ("Time Window",      "09:45 – 14:30 ET"),
            ("Volume Gate",      "RVOL ≥ 150% on the candle entering the gap"),
            ("Gap Freshness",    "FVG zone must have been created within the last 20 bars"),
            ("Confidence Range", "0.63 – 0.81"),
            ("Chart DNA",        "Look for: 3-bar imbalance zone → price drops away → returns to gap midpoint"),
            ("Direction",        "Bullish FVG (gap above): PUT when price falls back into it. Bearish FVG (gap below): CALL when price rises to it."),
            ("What to watch",    "The gap zone appears as shaded area if structure overlays are on · entry at zone midpoint"),
        ], color="#ec4899")
        st.plotly_chart(
            _build_strategy_fig("fvg", seed=44),
            use_container_width=True,
        )
        st.info(
            "**Think of an FVG like a pothole in the road.** Price moved so fast it left a hole. "
            "When it comes back, it fills the hole before continuing. "
            "The bot doesn't chase price away from the gap — it waits for the return."
        )
    
    # ── Tab 5: MID_BRK ───────────────────────────────────────────────────────
    with _pb_tabs[4]:
        st.markdown("**MID_BRK — Midday Breakdown**")
        st.markdown(
            "After the morning session, price often consolidates or drifts. "
            "A Midday Breakdown happens when price — already in a confirmed downtrend — finally breaks "
            "below the OR Low in the 11:00–13:30 window. This is a continuation play: the morning "
            "established the direction, midday adds another leg. Requires a confirmed Lower High before entry."
        )
        _strat_card([
            ("Trigger",          "Close breaks below OR Low in confirmed downtrend · confirmed Lower High on record"),
            ("Time Window",      "11:00 – 13:30 ET only (mid-session window)"),
            ("Volume Gate",      "RVOL ≥ 150% on the breakdown candle"),
            ("Trend Context",    "MSA must show downtrend + at least one confirmed LH before the break"),
            ("VWAP Gate",        "Price must be below VWAP at entry"),
            ("Confidence Range", "0.67 – 0.83"),
            ("Chart DNA",        "Morning: SH → LH stair-step. Midday: price coils near OR Low → volume spike → clean break"),
            ("What to watch",    "The OR Low is the red dashed line. Entry fires when a 5m candle closes below it with volume."),
        ], color="#ef4444")
        st.plotly_chart(
            _build_strategy_fig("mid_brk", seed=45),
            use_container_width=True,
        )
        st.info(
            "**This is a second-leg trade.** The morning gave you the trend (LH pattern). "
            "Midday gave you the re-test. The breakdown candle is your signal. "
            "If RVOL is below 1.5× or the LH was not confirmed, the bot passes — midday traps are common."
        )
    
    # ── Tab 6: AFT_REV ───────────────────────────────────────────────────────
    with _pb_tabs[5]:
        st.markdown("**AFT_REV — Afternoon Reversal**")
        st.markdown(
            "The afternoon session (13:30–15:00) often sees institutions repositioning. "
            "After a morning downtrend, a Higher Low forms — sellers are exhausted. "
            "When price then breaks above the most recent Lower High, the downtrend structure is broken "
            "and a reversal is underway. The bot buys the Break of Structure to the upside."
        )
        _strat_card([
            ("Trigger",          "Close breaks above last confirmed Lower High (CALL) — Break of Structure to upside"),
            ("Time Window",      "13:30 – 15:00 ET only (afternoon window)"),
            ("Volume Gate",      "RVOL ≥ 150% on the break candle"),
            ("Trend Context",    "Must have confirmed Higher Low (HL) before the break — proves sellers exhausted"),
            ("Confidence Range", "0.65 – 0.82"),
            ("Chart DNA",        "Morning: SH → LH → SL → LL. Afternoon: HL forms → price breaks above last LH"),
            ("What to watch",    "The LH label on the chart is the resistance level. Entry fires when price closes above it."),
            ("Pro tip",          "Best reversals have the HL near VWAP and the LH break on above-average volume"),
        ], color="#22c55e")
        st.plotly_chart(
            _build_strategy_fig("aft_rev", seed=46),
            use_container_width=True,
        )
        st.info(
            "**The reversal is confirmed, not anticipated.** The bot does not enter at the HL. "
            "It waits for price to actually break above the LH with volume. "
            "That break is your signal that institutions are stepping in on the buy side."
        )
    
    # ── Tab 7: TREND_CONT ─────────────────────────────────────────────────────
    with _pb_tabs[6]:
        st.markdown("**TREND_CONT — Trend Continuation (Lower High / Higher Low Re-entry)**")
        st.markdown(
            "Once a trend is established, experienced traders re-enter on pullbacks rather than chasing. "
            "In a downtrend, price pulls back to form a Lower High (LH) — resistance — then resumes lower. "
            "The bot enters when the current bar closes below the LH bar's close, confirming the pullback failed "
            "and the downtrend is resuming. In an uptrend, the inverse: enter when price bounces off a Higher Low."
        )
        _strat_card([
            ("Trigger",          "Downtrend: close < LH bar close after confirmed LH (PUT) · Uptrend: close > HL bar close after confirmed HL (CALL)"),
            ("Time Window",      "09:45 – 14:30 ET"),
            ("Volume Gate",      "RVOL ≥ 120% (lower gate — trend already established)"),
            ("Trend Context",    "MSA must confirm downtrend/uptrend · LH must be within last 10 bars"),
            ("VWAP Gate",        "Price below VWAP for PUT · above VWAP for CALL"),
            ("Confidence Range", "0.65 – 0.82"),
            ("Chart DNA",        "Look for: clear LH/HL annotation within 10 bars · price pulling back into it · then rejection candle"),
            ("What to watch",    "The rejection candle is the signal. Entry is the bar after it closes in trend direction."),
        ], color="#8b5cf6")
        st.plotly_chart(
            _build_strategy_fig("trend_cont", seed=47),
            use_container_width=True,
        )
        st.info(
            "**This is an expert re-entry trade.** Amateurs chase the initial move. "
            "Professionals wait for the first pullback to form a LH (in a downtrend) and enter when "
            "the pullback fails. Lower RVOL gate (1.2×) is allowed because the trend is already confirmed — "
            "you need less new participation to sustain an existing move."
        )
    
    # ── Tab 8: CHAN_BREAK ─────────────────────────────────────────────────────
    with _pb_tabs[7]:
        st.markdown("**CHAN_BREAK — Channel Trendline Rejection**")
        st.markdown(
            "When price makes two or more Lower Highs, a descending channel trendline can be drawn through them. "
            "That line becomes dynamic resistance — every time price tags it and rejects, it's a short entry. "
            "The bot projects the trendline forward in real-time. When the current bar's high tags the projected "
            "line within 0.3% and the bar closes below it, a rejection is confirmed."
        )
        _strat_card([
            ("Trigger",          "Current bar high within 0.3% of projected descending trendline · close below the line"),
            ("Time Window",      "09:45 – 14:00 ET"),
            ("Volume Gate",      "RVOL ≥ 130% on the rejection candle"),
            ("Channel Requirement", "≥ 2 confirmed swing highs forming the descending line · both within last 40 bars"),
            ("Slope Gate",       "Slope must exceed 0.002 (minimum angle — flat lines rejected)"),
            ("Confidence Range", "0.75 – 0.90 (highest ceiling of all strategies)"),
            ("Chart DNA",        "Descending dashed channel line on chart · rejection candle has a wick touching the line, body closes below"),
            ("What to watch",    "Ascending channel = lower trendline is support → CALL when price bounces off it with volume"),
        ], color="#f97316")
        st.plotly_chart(
            _build_strategy_fig("chan_break", seed=48),
            use_container_width=True,
        )
        st.info(
            "**This is precision trading.** The trendline is your edge. "
            "When price taps the line for the third time and rejects, institutions have sold into that resistance "
            "twice before and are doing it again. The wick above the line with a body close below = clean rejection. "
            "This strategy has the highest confidence ceiling (0.90) because the setup is so specific."
        )
    
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
    

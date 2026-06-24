"""
dashboard/pages/performance.py — Performance page.

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
    """Render the Performance page."""
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
    

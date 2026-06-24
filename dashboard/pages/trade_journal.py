"""
dashboard/pages/trade_journal.py — Trade Journal page.

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
    """Render the Trade Journal page."""
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
    

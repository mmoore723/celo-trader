"""
dashboard/helpers.py — Shared utility functions used by all pages.

Import:
    from dashboard.helpers import (
        _read_bot_state, _bot_engine_alive, generate_simulation_data,
        _load_sim_bars, _html_table, _to_et_isoformat, _live_balance,
        _BOT_STATE_PATH,
    )
"""
import json
import math
import threading
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

from config import get_settings, STARTING_CAPITAL, DB_PATH_PAPER, DB_PATH_LIVE
from trading_logic import LIVE_STATE
from broker import get_clients

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
        _yf_df = _yf.download(ticker, period="2d", interval=_yf_interval,
                               progress=False, auto_adjust=True)
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
            # Keep only regular-session bars (09:29–16:01) and the last calendar day
            _yf_df = _yf_df[
                (_yf_df["time"].dt.hour > 9) |
                ((_yf_df["time"].dt.hour == 9) & (_yf_df["time"].dt.minute >= 29))
            ]
            _yf_df = _yf_df[_yf_df["time"].dt.hour < 16]
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


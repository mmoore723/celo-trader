"""
strategy_health/engine.py — replay real strategy code against real market
data for the most recent complete trading day, one ticker at a time.

This generalizes what diag_mid_brk_adx_funnel.py did for one strategy into
a permanent, all-strategy check: at every bar, call the REAL
strategy_router.route_signals() (the exact code path live/backtest uses) to
see what actually survives every gate, AND call each strategy's raw
evaluate() directly to see what it would have found before any gate ran.
The gap between the two numbers is the router's real, measured impact —
no gate logic is reimplemented or guessed at here.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Optional

import pandas as pd

from broker import AlpacaClient
from signals import bars_to_df
import strategy_router as _router

logger = logging.getLogger("celo_trader.strategy_health.engine")

# How many 5-min bars to pull per ticker. ~78 bars/session -> ~19 sessions,
# enough history for RVOL(10-day) and ADX(14) baselines plus the target day.
_BARS_LOOKBACK = 1500
FORWARD_BARS   = 12   # 12 x 5-min = 60 minutes, same proxy used across diag_*.py


def _fetch_bars(alpaca: AlpacaClient, ticker: str) -> pd.DataFrame:
    """Real Alpaca bars only — this runs live in production, no yfinance fallback."""
    try:
        raw, is_error = alpaca.get_bars(ticker, "5Min", limit=_BARS_LOOKBACK)
        if is_error or not raw:
            return pd.DataFrame()
        return bars_to_df(raw)
    except Exception as exc:
        logger.warning("strategy_health: bar fetch failed for %s: %s", ticker, exc)
        return pd.DataFrame()


def audit_ticker(alpaca: AlpacaClient, ticker: str) -> Optional[dict]:
    """
    Replay the most recent complete trading day for `ticker` bar-by-bar.

    Returns a dict:
      {
        "ticker": str, "date": "YYYY-MM-DD",
        "per_strategy": {
            strategy_id: {
                "raw_signals": int,             # evaluate() fired, pre-gate
                "router_survivors": int,        # also present in route_signals() output
                "avg_confidence_raw": float,
                "worked_raw": int,               # 60-min forward move agreed with direction
                "worked_survivors": int,
            }, ...
        }
      }
    or None if there's not enough data to say anything meaningful.
    """
    df = _fetch_bars(alpaca, ticker)
    if df.empty or len(df) < 100:
        return None

    target_date = df["time"].dt.date.max()
    day_df = df[df["time"].dt.date == target_date].reset_index(drop=True)
    if len(day_df) < 15:
        return None

    per_strategy: dict = defaultdict(lambda: {
        "raw_signals": 0, "router_survivors": 0,
        "_raw_conf_sum": 0.0, "worked_raw": 0, "worked_survivors": 0,
    })

    for i in range(10, len(day_df)):
        bar_time = day_df.iloc[i]["time"]
        df_upto  = df[df["time"] <= bar_time].reset_index(drop=True)

        # ── Real, unmodified pipeline: what actually survives to be tradeable ──
        try:
            survivors = _router.route_signals(df_upto, ticker=ticker)
        except Exception as exc:
            logger.debug("route_signals failed at %s %s: %s", ticker, bar_time, exc)
            survivors = []
        survivor_ids = {s.strategy_id for s in survivors}

        # ── Raw: each strategy's own evaluate(), bypassing every router gate ──
        today_frame = _router._build_indicator_frame(df_upto)
        if today_frame.empty:
            continue

        fwd_idx  = i + FORWARD_BARS
        fwd_pct  = None
        if fwd_idx < len(day_df):
            entry_px = float(day_df.iloc[i]["close"])
            fwd_px   = float(day_df.iloc[fwd_idx]["close"])
            fwd_pct  = (fwd_px - entry_px) / entry_px * 100

        for strategy_id, fn in _router.ACTIVE_STRATEGIES:
            try:
                sig = fn(today_frame, ticker=ticker)
            except Exception:
                continue
            if sig is None:
                continue

            row = per_strategy[strategy_id]
            row["raw_signals"] += 1
            row["_raw_conf_sum"] += sig.confidence

            if fwd_pct is not None:
                agreed = (fwd_pct > 0.10) if sig.direction == "bullish" else (fwd_pct < -0.10)
                if agreed:
                    row["worked_raw"] += 1
                    if strategy_id in survivor_ids:
                        row["worked_survivors"] += 1

            if strategy_id in survivor_ids:
                row["router_survivors"] += 1

    # Finalize averages, drop the private accumulator
    result: dict = {}
    for strategy_id, row in per_strategy.items():
        n = row["raw_signals"]
        result[strategy_id] = {
            "raw_signals":       n,
            "router_survivors":  row["router_survivors"],
            "avg_confidence_raw": round(row["_raw_conf_sum"] / n, 3) if n else 0.0,
            "worked_raw":        row["worked_raw"],
            "worked_survivors":  row["worked_survivors"],
        }

    if not result:
        return None

    return {"ticker": ticker, "date": str(target_date), "per_strategy": result}

"""
diag_mid_brk_level_scan.py — Fast, broad A/B scan for MID_BRK's reference
level (15-min OR vs 45-min consolidation range) without the full Backtester.

Why this exists: ab_test_mid_brk_consolidation.py returned 0 trades on BOTH
variants after ~an hour. Two real reasons, not bad luck:
  1. backtester.py hard-caps 5-min bar history at 59 days regardless of the
     `months` argument (yfinance's own limit) — asking for "3 months" was
     silently truncated the whole time. More months would never have helped.
  2. Backtester.run() simulates ALL 7 strategies' full options-pricing/exit
     machinery every tick, even when only one strategy's stats are wanted —
     that's most of the runtime, spent on nothing we needed.

This script fixes both: it scans a much broader ticker list (more chances
at a rare setup within the same fixed ~59-day window) and calls ONLY
mid_brk.evaluate() bar-by-bar — the real strategy code, unmodified — with
no options simulation at all. Quality is judged by a simple, fast proxy:
the underlying's own % move over the next 60 minutes, signed by direction
(bearish signal + price kept falling = "worked"). This is not exact trade
P&L, but it's dramatically cheaper and enough to see whether the wider
consolidation range finds MORE and/or BETTER setups than the narrow OR.

Usage:
    python3 diag_mid_brk_level_scan.py                     # default ticker list
    python3 diag_mid_brk_level_scan.py SPY QQQ NVDA AAPL
"""

from __future__ import annotations

import sys

import pandas as pd

from broker import AlpacaClient
from signals import bars_to_df, compute_rvol
import strategies.mid_brk as mid_brk

DEFAULT_TICKERS = ["SPY", "QQQ", "NVDA", "AAPL", "TSLA", "AMD", "META", "AMZN", "MSFT", "GOOGL"]
FORWARD_BARS    = 12   # 12 x 5-min = 60 minutes


def _fetch_bars(alpaca: AlpacaClient, ticker: str) -> pd.DataFrame:
    """Same yfinance-first, Alpaca-fallback approach as backtester.py, trimmed."""
    import datetime as _dt
    df = pd.DataFrame()
    try:
        import yfinance as yf
        _today   = _dt.date.today()
        _start_d = (_today - _dt.timedelta(days=59)).strftime("%Y-%m-%d")
        _end_d   = (_today + _dt.timedelta(days=1)).strftime("%Y-%m-%d")
        raw = yf.download(ticker, start=_start_d, end=_end_d, interval="5m",
                           progress=False, auto_adjust=True)
        if not raw.empty:
            if hasattr(raw.columns, "get_level_values"):
                raw.columns = raw.columns.get_level_values(0)
            raw = raw.rename(columns={"Open": "open", "High": "high", "Low": "low",
                                       "Close": "close", "Volume": "volume"})
            raw.index.name = "time"
            raw = raw.reset_index()
            raw["time"] = (pd.to_datetime(raw["time"], utc=True)
                            .dt.tz_convert("America/New_York").dt.tz_localize(None))
            df = raw[["time", "open", "high", "low", "close", "volume"]].copy()
    except Exception:
        pass

    if df.empty:
        raw2 = alpaca.get_bars(ticker, "5Min", limit=10000)
        bars = raw2[0] if isinstance(raw2, tuple) else raw2
        if bars:
            df = bars_to_df(bars)
    return df


def _build_frame(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["rvol"]      = compute_rvol(df, lookback_days=10)
    df["ema50"]     = df["close"].ewm(span=50, adjust=False).mean()
    df["vol_sma20"] = df["volume"].rolling(100, min_periods=20).mean()
    hl  = df["high"] - df["low"]
    hcp = (df["high"] - df["close"].shift(1)).abs()
    lcp = (df["low"]  - df["close"].shift(1)).abs()
    tr  = pd.concat([hl, hcp, lcp], axis=1).max(axis=1)
    df["atr"] = tr.ewm(span=14, adjust=False).mean()

    from signals import compute_vwap_bands
    vwap_frame = compute_vwap_bands(df, num_stds=(1, 2))
    df["vwap"] = vwap_frame["vwap"].ffill()
    return df


def _scan_ticker(df: pd.DataFrame, ticker: str, enabled: bool) -> list[dict]:
    mid_brk.CONSOLIDATION_RANGE_ENABLED = enabled
    signals_found = []
    df["_date"] = df["time"].dt.date
    for day, day_df in df.groupby("_date"):
        day_df = day_df.reset_index(drop=True)
        if len(day_df) < 15:
            continue
        for i in range(10, len(day_df)):
            slice_df = day_df.iloc[: i + 1].reset_index(drop=True)
            try:
                sig = mid_brk.evaluate(slice_df, ticker=ticker)
            except Exception:
                continue
            if sig is None:
                continue
            # Forward return proxy: underlying % move over the next 60 min
            fwd_idx = i + FORWARD_BARS
            if fwd_idx < len(day_df):
                entry_px = float(day_df.iloc[i]["close"])
                fwd_px   = float(day_df.iloc[fwd_idx]["close"])
                fwd_pct  = (fwd_px - entry_px) / entry_px * 100
                # MID_BRK is bearish-only — a "win" is price continuing DOWN
                worked = fwd_pct < -0.10
                signals_found.append({
                    "ticker": ticker, "date": str(day), "time": str(day_df.iloc[i]["time"]),
                    "confidence": sig.confidence, "fwd_pct": round(fwd_pct, 3),
                    "worked": worked,
                })
    return signals_found


def main() -> None:
    tickers = [t.upper() for t in sys.argv[1:]] or DEFAULT_TICKERS
    alpaca  = AlpacaClient()

    _orig = mid_brk.CONSOLIDATION_RANGE_ENABLED
    all_old, all_new = [], []
    try:
        for ticker in tickers:
            print(f"⏳ {ticker}…", flush=True)
            df = _fetch_bars(alpaca, ticker)
            if df.empty or len(df) < 50:
                print(f"  (no usable data for {ticker}, skipping)")
                continue
            df = _build_frame(df)
            all_old.extend(_scan_ticker(df, ticker, enabled=False))
            all_new.extend(_scan_ticker(df, ticker, enabled=True))
    finally:
        mid_brk.CONSOLIDATION_RANGE_ENABLED = _orig

    def _report(name: str, rows: list[dict]) -> None:
        n = len(rows)
        if n == 0:
            print(f"{name:<28} 0 signals found.")
            return
        wins = sum(1 for r in rows if r["worked"])
        avg_fwd = sum(r["fwd_pct"] for r in rows) / n
        print(f"{name:<28} signals={n:>4}  'worked'(price kept falling)={wins:>3} "
              f"({wins/n*100:.0f}%)  avg 60m fwd move={avg_fwd:+.3f}%")

    print("\n" + "=" * 90)
    print(f"MID_BRK REFERENCE-LEVEL SCAN — {len(tickers)} ticker(s), ~59-day window")
    print("(quality proxy: underlying's own 60-min forward move, NOT full options P&L)")
    print("=" * 90)
    _report("15-MIN OR (old, live default)", all_old)
    _report("45-MIN CONSOLIDATION (new)", all_new)

    print("\nThis is a fast screen, not a final verdict. If the new variant shows more")
    print("signals AND a higher 'worked' rate / more negative avg forward move, it's")
    print("worth then running the full ab_test_mid_brk_consolidation.py backtest on")
    print("just those tickers/months to confirm real P&L before shipping.")


if __name__ == "__main__":
    main()

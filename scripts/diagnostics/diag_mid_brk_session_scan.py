"""
diag_mid_brk_session_scan.py — Where do MID_BRK-shaped setups actually occur
during the day, and is the 10:30-13:00 session window cutting off real ones?

Why this exists: the consolidation-range fix (ab_test_mid_brk_consolidation.py
/ diag_mid_brk_level_scan.py) came back marginal — not a clear win. The chart
audit that started this whole investigation found SPY's real 2026-07-16
breakdown didn't clear either reference level until AFTER MID_BRK's 13:00
cutoff. That points at the session window itself, not the OR-vs-consolidation
distinction, as the real gap.

This script disables the session gate entirely (bypasses _SESSION_START_MIN/
_SESSION_END_MIN in strategies/mid_brk.py via module-attribute mutation, same
technique used for _MAX_BARS in trend_cont.py) and lets the REAL, unmodified
evaluate() fire at any hour. Every signal found is bucketed by the hour it
fired in, so we can see how many "worked" (price kept falling, same 60-min
forward-return proxy as diag_mid_brk_level_scan.py) inside the current
10:30-13:00 window vs. outside it.

This is a fast screen (forward-return proxy, no options P&L) meant to answer
one question: is there enough real signal after 13:00 to justify extending
the window and then running a proper A/B backtest? It does not, by itself,
justify shipping anything.

Usage:
    python3 diag_mid_brk_session_scan.py                     # default ticker list
    python3 diag_mid_brk_session_scan.py SPY QQQ NVDA AAPL
"""

from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root, needed after this script's move into scripts/<subdir>/
from collections import defaultdict

import pandas as pd

from broker import AlpacaClient
from signals import bars_to_df, compute_rvol, compute_vwap_bands
import strategies.mid_brk as mid_brk

DEFAULT_TICKERS = ["SPY", "QQQ", "NVDA", "AAPL", "TSLA", "AMD", "META", "AMZN", "MSFT", "GOOGL"]
FORWARD_BARS    = 12   # 12 x 5-min = 60 minutes

# Current live window, for bucketing "inside" vs "outside" in the report.
_LIVE_START = 10 * 60 + 30
_LIVE_END   = 13 * 60


def _fetch_bars(alpaca: AlpacaClient, ticker: str) -> pd.DataFrame:
    """
    Same yfinance-first, Alpaca-fallback approach as diag_mid_brk_level_scan.py.

    FIX 2026-07-23: this always re-fetched from scratch, even on a rerun the
    same day — this script's window (59 days) never changes within a day, so
    it's a perfect fit for backtest_data_cache.py's raw-bars cache (shared
    with every other script, not just this one). See that module's docstring.
    """
    import backtest_data_cache
    _cached = backtest_data_cache.load_raw_bars(ticker)
    if _cached is not None:
        return _cached

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
    if not df.empty:
        backtest_data_cache.save_raw_bars(ticker, df)
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
    vwap_frame = compute_vwap_bands(df, num_stds=(1, 2))
    df["vwap"] = vwap_frame["vwap"].ffill()
    return df


def _scan_ticker(df: pd.DataFrame, ticker: str) -> list[dict]:
    found = []
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
            bar_time = day_df.iloc[i]["time"]
            bar_min  = bar_time.hour * 60 + bar_time.minute
            fwd_idx  = i + FORWARD_BARS
            if fwd_idx < len(day_df):
                entry_px = float(day_df.iloc[i]["close"])
                fwd_px   = float(day_df.iloc[fwd_idx]["close"])
                fwd_pct  = (fwd_px - entry_px) / entry_px * 100
                worked   = fwd_pct < -0.10   # bearish-only: "worked" = kept falling
                found.append({
                    "ticker": ticker, "date": str(day), "time": str(bar_time),
                    "bar_min": bar_min, "hour": bar_time.hour,
                    "confidence": sig.confidence, "fwd_pct": round(fwd_pct, 3),
                    "worked": worked,
                    "in_live_window": _LIVE_START <= bar_min <= _LIVE_END,
                })
    return found


def main() -> None:
    tickers = [t.upper() for t in sys.argv[1:]] or DEFAULT_TICKERS
    alpaca  = AlpacaClient()

    # Disable the session gate entirely for this scan — let the REAL evaluate()
    # fire at any hour so we can see where structural setups actually cluster.
    orig_start, orig_end = mid_brk._SESSION_START_MIN, mid_brk._SESSION_END_MIN
    all_signals: list[dict] = []
    try:
        mid_brk._SESSION_START_MIN = 0
        mid_brk._SESSION_END_MIN   = 24 * 60
        for ticker in tickers:
            print(f"⏳ {ticker}…", flush=True)
            df = _fetch_bars(alpaca, ticker)
            if df.empty or len(df) < 50:
                print(f"  (no usable data for {ticker}, skipping)")
                continue
            df = _build_frame(df)
            all_signals.extend(_scan_ticker(df, ticker))
    finally:
        mid_brk._SESSION_START_MIN = orig_start
        mid_brk._SESSION_END_MIN   = orig_end

    print("\n" + "=" * 92)
    print(f"MID_BRK SESSION-WINDOW SCAN — {len(tickers)} ticker(s), ~59-day window, session gate disabled")
    print("(quality proxy: underlying's own 60-min forward move, NOT full options P&L)")
    print("=" * 92)

    by_hour: dict[int, list[dict]] = defaultdict(list)
    for s in all_signals:
        by_hour[s["hour"]].append(s)

    total = len(all_signals)
    print(f"\nTotal raw structural signals found (all hours, session gate off): {total}\n")
    print(f"{'Hour (ET)':<12}{'signals':>9}{'worked':>9}{'worked%':>10}{'avg fwd%':>12}{'in live window?':>18}")
    for hour in sorted(by_hour):
        rows = by_hour[hour]
        n    = len(rows)
        wins = sum(1 for r in rows if r["worked"])
        avg  = sum(r["fwd_pct"] for r in rows) / n
        in_window = "yes" if (_LIVE_START <= hour * 60 <= _LIVE_END) else "no"
        print(f"{hour:>2}:00{'':<7}{n:>9}{wins:>9}{wins/n*100:>9.0f}%{avg:>+11.3f}%{in_window:>18}")

    inside  = [s for s in all_signals if s["in_live_window"]]
    outside = [s for s in all_signals if not s["in_live_window"]]

    def _summary(name: str, rows: list[dict]) -> None:
        n = len(rows)
        if n == 0:
            print(f"{name:<40} 0 signals.")
            return
        wins = sum(1 for r in rows if r["worked"])
        avg  = sum(r["fwd_pct"] for r in rows) / n
        print(f"{name:<40} signals={n:>4}  worked={wins:>3} ({wins/n*100:.0f}%)  avg 60m fwd={avg:+.3f}%")

    print("\n" + "-" * 92)
    _summary("INSIDE current 10:30-13:00 window", inside)
    _summary("OUTSIDE current window (candidate extension)", outside)

    print("\nIf 'OUTSIDE' shows a meaningful volume of signals with a comparable or")
    print("better worked%/avg-fwd-move than 'INSIDE', extending _SESSION_END_MIN is")
    print("worth a real A/B backtest (ab_test_mid_brk_session_window.py). If outside")
    print("signals are rare or lower quality, the 13:00 cutoff is fine as-is and the")
    print("07-16 miss was a one-off, not a structural gap.")


if __name__ == "__main__":
    main()

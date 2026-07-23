"""
diag_1min_data_availability.py — Checks how much 1-minute bar history is
actually available from yfinance AND Alpaca before committing to a
backtester.py rewrite that scans entries on 1-min bars (matching live's
entry.py, which explicitly runs on 1-min bars — see trading/entry.py's
"Switched from 5Min -> 1Min" comment).

WHY THIS CHECK FIRST: yfinance's 5-minute bars are capped at ~60 days
(the limit we've hit repeatedly all session). 1-minute bars are known to
have a MUCH shorter retention window historically (~7 days) — if that's
still true, rewriting the backtester for 1-min entries could leave us with
too few trades per ticker to test anything meaningfully, which would
undercut the in/out-of-sample sweep tool planned right after this fix.
Alpaca's free/IEX tier might have deeper 1-min history than yfinance —
worth checking both before deciding the approach.

This makes NO changes to the app — pure read-only diagnostic.

Usage:
    python3 diag_1min_data_availability.py
    python3 diag_1min_data_availability.py SPY QQQ
"""

from __future__ import annotations

import sys
import datetime as dt


def check_yfinance(ticker: str) -> None:
    print(f"\n--- yfinance 1m check: {ticker} ---")
    try:
        import yfinance as yf
    except ImportError:
        print("  yfinance not installed — skip")
        return

    for days_back in (7, 14, 30, 60):
        start = (dt.date.today() - dt.timedelta(days=days_back)).strftime("%Y-%m-%d")
        end   = (dt.date.today() + dt.timedelta(days=1)).strftime("%Y-%m-%d")
        try:
            df = yf.download(ticker, start=start, end=end, interval="1m",
                              progress=False, auto_adjust=True)
            n = len(df)
            earliest = df.index.min() if n else None
            print(f"  requested {days_back:>3}d back -> got {n:>5} bars"
                  f"{'  earliest=' + str(earliest) if earliest is not None else ''}")
        except Exception as ex:
            print(f"  requested {days_back:>3}d back -> ERROR: {ex}")


def check_alpaca(ticker: str) -> None:
    print(f"\n--- Alpaca 1Min check: {ticker} (post broker.py fix) ---")
    try:
        from broker import AlpacaClient
        alpaca = AlpacaClient()
    except Exception as ex:
        print(f"  AlpacaClient init failed: {ex} — skip")
        return

    # 2026-07-21: broker.py's day-count math for "1Min" was fixed (was using
    # the 5Min rate, 5x too low). Test a range of limits post-fix to find the
    # real depth Alpaca's free/IEX tier actually serves.
    for limit in (10000, 30000, 60000):
        try:
            bars, is_error = alpaca.get_bars(ticker, "1Min", limit=limit)
            n = len(bars) if bars else 0
            print(f"  limit={limit:>6} -> got {n:>6} bars, is_error={is_error}")
            if bars:
                from signals import bars_to_df
                df = bars_to_df(bars)
                if not df.empty:
                    print(f"      earliest={df['time'].min()}  latest={df['time'].max()}")
        except Exception as ex:
            print(f"  limit={limit:>6} -> ERROR: {ex}")


def main() -> None:
    tickers = sys.argv[1:] or ["SPY"]
    for t in tickers:
        check_yfinance(t)
        check_alpaca(t)
    print("\nReport back: how many days of 1-minute bars are actually available")
    print("from each source, so the resolution fix can be scoped correctly.")


if __name__ == "__main__":
    main()

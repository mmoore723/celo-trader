"""
diag_entry_resolution_comparison.py — Measures how much entry-signal
detection actually differs between 1-minute and 5-minute bar resolution.

WHY THIS, NOT A FULL BACKTESTER REWRITE: rewriting backtester.py's trade
simulation to tick on 1-minute bars would mean restructuring the exit
engine fixed earlier today (real risk factor: reintroducing bugs into
code that just got correct). This script instead calls strategy_router.
route_signals() — the REAL, unmodified live signal-detection pipeline,
gates and all — directly against both resolutions, with no simulated
trades and no duplicated gate logic. Pure signal-detection comparison,
answering "does entry timing/resolution actually matter" before
committing to the bigger, riskier rewrite.

METHOD: for each trading day, walk forward in wall-clock time. At each
1-minute mark, ask two questions using the real router: (a) does the
1-minute view (all 1-min bars up to right now) see a tradeable signal
yet, and (b) does the 5-minute view (only the 5-min bars that have
actually CLOSED by this wall-clock moment) see one yet. First-fire time
and price are recorded for each. This directly measures how much lag/
price-slippage the coarser resolution introduces, using the exact same
route_signals() live calls every tick — not an approximation.

DATA: Alpaca 1-minute bars (yfinance caps 1-minute history at 8 days,
confirmed too short to be useful here — see diag_1min_data_availability.py).
Alpaca's free/IEX tier reliably serves ~36 days after the broker.py fix
(2026-07-21); this script only compares days where BOTH the 1-min and
5-min fetches have data, which caps the window to whichever is smaller.

Usage:
    python3 diag_entry_resolution_comparison.py SPY QQQ NVDA
"""

from __future__ import annotations

import sys

import pandas as pd

from broker import AlpacaClient
from signals import bars_to_df
from strategy_router import route_signals
from backtester_1min_entry import fetch_1min_entry_data

DEFAULT_TICKERS = ["SPY", "QQQ", "NVDA"]


def _fetch_5min(alpaca, ticker: str, days: int) -> pd.DataFrame | None:
    # 2026-07-21: kept deliberately small and aligned with the 1-min fetch's
    # real depth (~31 calendar days, see backtester_1min_entry.py's
    # _SAFE_1MIN_LIMIT) — only the overlap between the two fetches matters
    # for this comparison, so there's no benefit to requesting a wider
    # 5-min window than the 1-min side can ever match, and doing so risks
    # the same oversized-request 400 error found in the 1-min fetch above.
    bars, is_error = alpaca.get_bars(ticker, "5Min", limit=days * 78)
    if is_error or not bars:
        return None
    df = bars_to_df(bars)
    if df.empty:
        return None
    df["_date"] = df["time"].dt.date
    return df


def _compare_ticker(alpaca, ticker: str) -> dict | None:
    df_1m = fetch_1min_entry_data(alpaca, ticker, months=2)
    if df_1m is None:
        print(f"  {ticker}: no 1-min data available — skip")
        return None
    df_5m = _fetch_5min(alpaca, ticker, days=20)  # kept well under the 1-min fetch's ~31-day depth
    if df_5m is None or df_5m.empty:
        print(f"  {ticker}: no 5-min data available — skip")
        return None

    common_dates = sorted(set(df_1m["_date"].unique()) & set(df_5m["_date"].unique()))
    if not common_dates:
        print(f"  {ticker}: no overlapping days between the two fetches — skip")
        return None

    both, only_1m, only_5m = 0, 0, 0
    lags_min, price_diffs_pct = [], []

    for d in common_dates:
        day_1m = df_1m[df_1m["_date"] == d].reset_index(drop=True)
        day_5m = df_5m[df_5m["_date"] == d].reset_index(drop=True)
        if len(day_1m) < 25 or len(day_5m) < 5:
            continue

        first_1m_time = first_1m_price = None
        first_5m_time = first_5m_price = None

        for i in range(20, len(day_1m)):
            t = day_1m["time"].iloc[i]

            if first_1m_time is None:
                sig = route_signals(day_1m.iloc[: i + 1], ticker, quiet=True)
                if sig:
                    first_1m_time  = t
                    first_1m_price = float(day_1m["close"].iloc[i])

            if first_5m_time is None:
                visible_5m = day_5m[day_5m["time"] <= t]
                if len(visible_5m) >= 5:
                    sig5 = route_signals(visible_5m, ticker, quiet=True)
                    if sig5:
                        first_5m_time  = visible_5m["time"].iloc[-1]
                        first_5m_price = float(visible_5m["close"].iloc[-1])

            if first_1m_time is not None and first_5m_time is not None:
                break

        if first_1m_time is not None and first_5m_time is not None:
            both += 1
            lags_min.append((first_5m_time - first_1m_time).total_seconds() / 60)
            price_diffs_pct.append(
                abs(first_5m_price - first_1m_price) / first_1m_price * 100
            )
        elif first_1m_time is not None:
            only_1m += 1
        elif first_5m_time is not None:
            only_5m += 1

    return {
        "ticker": ticker, "days_compared": len(common_dates),
        "both_detected": both, "only_1min_detected": only_1m,
        "only_5min_detected": only_5m,
        "avg_lag_min": round(sum(lags_min) / len(lags_min), 1) if lags_min else None,
        "avg_price_diff_pct": round(sum(price_diffs_pct) / len(price_diffs_pct), 2) if price_diffs_pct else None,
    }


def main() -> None:
    tickers = sys.argv[1:] or DEFAULT_TICKERS
    alpaca = AlpacaClient()
    results = []
    for t in tickers:
        print(f"\n=== {t} ===", flush=True)
        r = _compare_ticker(alpaca, t)
        if r:
            results.append(r)

    print("\n" + "=" * 78)
    print("ENTRY RESOLUTION COMPARISON RESULT")
    print("=" * 78)
    for r in results:
        print(f"{r['ticker']}: {r['days_compared']} days compared | "
              f"both={r['both_detected']} only_1min={r['only_1min_detected']} "
              f"only_5min={r['only_5min_detected']}")
        if r["avg_lag_min"] is not None:
            print(f"    when both detected it: 5-min view lagged 1-min view by "
                  f"{r['avg_lag_min']} min on average, price moved "
                  f"{r['avg_price_diff_pct']}% in that time")

    print("\nonly_1min = days the 1-min view caught a signal the 5-min view never saw that day.")
    print("A large only_1min count or large avg_lag_min is real evidence the resolution")
    print("mismatch matters. Small/zero numbers mean it's probably NOT the main lever —")
    print("in which case the bigger backtester rewrite likely isn't worth the risk.")


if __name__ == "__main__":
    main()

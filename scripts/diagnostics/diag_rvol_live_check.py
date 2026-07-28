"""
diag_rvol_live_check.py — 2026-07-28, live RVOL investigation.

WHY THIS EXISTS: bot_tail.log shows RVOL reading exactly 0.0x across every
strategy and every ticker today (195/195 log lines), after reading normally
on Jul 19-22 (100% nonzero) and partially degrading Jul 23 (~17% nonzero).
compute_rvol() (signals.py) and get_session_bars() (broker.py) are both
unchanged in git since before the last real trade, so this isn't a simple
"which commit broke it" answer.

v1 of this script called broker.get_bars() directly and got clean, normal
RVOL — but that's NOT what the live bot calls. Traced the real path in
trading/entry.py::_tick() (~line 823-865):
  1. bars_5m = alpaca.get_session_bars(ticker, "1Min")   — today's session
  2. df5 = bars_to_df(bars_5m)                            — today, 1-min bars
  3. hist_bars = alpaca.get_bars(ticker, "5Min", limit=1500)  — ~15 days back
  4. df5 = concat(historical 5-min bars, today's 1-min bars)  — THIS is what
     actually gets passed to route_signals() → compute_rvol().

This script replicates that exact 4-step sequence instead of a simplified
version, so if the bug is in how these two different-resolution sources get
combined, it'll show up here too.

Run on your Mac (real Alpaca network access — the sandbox can't reach
data.alpaca.markets):
    python3 scripts/diagnostics/diag_rvol_live_check.py SPY QQQ NVDA
"""

from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
from broker import AlpacaClient
from signals import compute_rvol, bars_to_df

TICKERS = sys.argv[1:] or ["SPY", "QQQ", "NVDA"]


def main() -> None:
    alpaca = AlpacaClient()
    for ticker in TICKERS:
        print(f"\n=== {ticker} ===")

        # Step 1-2: today's session bars, exactly as _tick() does.
        try:
            bars_today, is_error, is_live = alpaca.get_session_bars(ticker, "1Min")
        except Exception as e:
            print(f"  ❌ get_session_bars raised: {e}")
            continue
        if is_error or not bars_today:
            print(f"  ❌ get_session_bars empty/error (is_error={is_error})")
            continue
        df_today = bars_to_df(bars_today)
        print(f"  today's 1-min bars: {len(df_today)}  |  last 5 volumes: {df_today['volume'].tail(5).tolist()}")
        print(f"  today zero-volume: {int((df_today['volume']==0).sum())}/{len(df_today)}")

        # Step 3: historical 5-min augment, exactly as _tick() does.
        try:
            hist_bars, hist_err = alpaca.get_bars(ticker, "5Min", limit=1500)
        except Exception as e:
            print(f"  ❌ get_bars (historical) raised: {e}")
            continue
        if hist_err or not hist_bars:
            print(f"  ⚠️  no historical bars returned (hist_err={hist_err}) — RVOL would fall back to 20-bar rolling mean")
            df_combined = df_today
        else:
            df_hist = bars_to_df(hist_bars)
            today_min = df_today["time"].min() if not df_today.empty else None
            if today_min is not None:
                df_hist = df_hist[df_hist["time"] < today_min]
            print(f"  historical 5-min bars (before today): {len(df_hist)}")
            if df_hist.empty:
                print("  ⚠️  historical set is EMPTY after the < today filter — this alone would zero out RVOL")
                df_combined = df_today
            else:
                df_combined = pd.concat([df_hist, df_today], ignore_index=True).sort_values("time").reset_index(drop=True)

        # Step 4: the actual compute_rvol() call route_signals() makes.
        rvol = compute_rvol(df_combined)
        last10_rvol = rvol.tail(10).round(3).tolist()
        n_zero_rvol = int(((rvol == 0) | rvol.isna()).sum())
        print(f"  compute_rvol() on COMBINED df — last 10: {last10_rvol}")
        print(f"  zero/NaN rvol: {n_zero_rvol}/{len(rvol)} ({n_zero_rvol/len(rvol)*100:.0f}%)")

        # Diagnose the timeframe-mismatch hypothesis directly: what fraction
        # of today's 1-min bars land on a :00/:05/:10... mark where a 5-min
        # historical bar could even exist to match against?
        if not df_today.empty:
            on_5min_mark = (df_today["time"].dt.minute % 5 == 0).mean()
            print(f"  fraction of today's bars on a 5-min mark (only ones that COULD match history): {on_5min_mark*100:.0f}%")

        if n_zero_rvol > len(rvol) * 0.5:
            print("  → VERDICT: RVOL zeroes out on the COMBINED (real pipeline) data even though today's raw volume is real.")
            print("             Likely cause: today is 1-min resolution, history is 5-min resolution — compute_rvol()")
            print("             matches by exact time-of-day, so most 1-min bars never find a historical match.")
        else:
            print("  → VERDICT: real pipeline looks normal here right now — today's live failure may be time-of-day specific.")


if __name__ == "__main__":
    main()

"""
ab_test_mid_brk_session_window.py — A/B test MID_BRK's session window:
10:30-13:00 (current live default) vs a candidate replacement window.

UPDATED 2026-07-23: diag_mid_brk_session_scan.py's per-HOUR breakdown (not
just inside/outside the current window) found the current window's own core
hours are its weakest: 13:00 was the worst hour scanned (27% worked, avg fwd
move actually went the WRONG way, +0.127%), while 11:00 was the best (65%
worked) and 14:00 had both strong quality (55% worked) AND by far the
largest sample (743 raw signals). That's why this script now takes a START
override too, not just an END extension — the real test isn't "trade longer,"
it's "skip the bad middle hour and trade where the data says the setups
actually work." Defaults below reflect that finding; override either via CLI
to test something else.

Run this AFTER diag_mid_brk_session_scan.py — that scan is a fast forward-
return proxy; this script confirms real P&L through the full options-pricing
Backtester before anything ships — same discipline as every other change in
this file: built OFF by default, flipped, compared, restored regardless of
outcome.

Usage:
    python3 ab_test_mid_brk_session_window.py                       # 3mo, SPY QQQ NVDA, shift to 13:30-15:00
    python3 ab_test_mid_brk_session_window.py 6 13:30 15:00 SPY QQQ NVDA
"""

from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root, needed after this script's move into scripts/<subdir>/

from broker import AlpacaClient
from backtester import Backtester
import strategies.mid_brk as mid_brk

DEFAULT_TICKERS = ["SPY", "QQQ", "NVDA"]
DEFAULT_MONTHS  = 3
DEFAULT_START   = "13:30"   # candidate new session start — skips the 12:00-13:00
DEFAULT_END     = "15:00"   # dead zone, lands in the 14:00 hour the scan liked best


def _parse_hhmm(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def _run_variant(alpaca, tickers, months, label: str) -> dict:
    trades, wins, pnl = 0, 0, 0.0
    for ticker in tickers:
        print(f"  ⏳ {label}: {ticker}…", flush=True)
        bt     = Backtester(alpaca, ticker, months=months, starting_capital=5000.0, direction="both")
        # MID_BRK is frozen in the live settings while its negative cohort is
        # investigated.  This controlled harness must explicitly opt it in or
        # it silently tests the current disabled configuration (zero trades).
        bt.enabled_strategies = set(bt.enabled_strategies) | {"MID_BRK"}
        result = bt.run()
        row    = (result.get("strategy_breakdown") or {}).get("MID_BRK", {})
        trades += int(row.get("trades", 0))
        wins   += int(row.get("wins", 0))
        pnl    += float(row.get("pnl", 0.0))
    return {"trades": trades, "wins": wins, "pnl": pnl}


def main() -> None:
    months     = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_MONTHS
    new_start  = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_START
    new_end    = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_END
    tickers    = sys.argv[4:] or DEFAULT_TICKERS
    new_start_min = _parse_hhmm(new_start)
    new_end_min   = _parse_hhmm(new_end)
    alpaca        = AlpacaClient()

    _orig_start = mid_brk._SESSION_START_MIN
    _orig_end   = mid_brk._SESSION_END_MIN
    try:
        print(f"\n=== VARIANT A: session 10:30-13:00 (current live default) ===")
        mid_brk._SESSION_START_MIN = 10 * 60 + 30
        mid_brk._SESSION_END_MIN   = 13 * 60
        old_result = _run_variant(alpaca, tickers, months, "10:30-13:00")

        print(f"\n=== VARIANT B: session {new_start}-{new_end} (data-driven candidate) ===")
        mid_brk._SESSION_START_MIN = new_start_min
        mid_brk._SESSION_END_MIN   = new_end_min
        new_result = _run_variant(alpaca, tickers, months, f"{new_start}-{new_end}")
    finally:
        # Always restore — this script must never leave live behavior changed
        mid_brk._SESSION_START_MIN = _orig_start
        mid_brk._SESSION_END_MIN   = _orig_end

    def _report(name: str, d: dict) -> None:
        n   = d["trades"]
        wr  = (d["wins"] / n * 100) if n else 0.0
        exp = (d["pnl"] / n) if n else 0.0
        print(f"{name:<24} trades={n:>4}  win%={wr:>5.1f}%  "
              f"total=${d['pnl']:>+9.2f}  expectancy=${exp:>+8.2f}/trade")

    print("\n" + "=" * 78)
    print("MID_BRK SESSION-WINDOW A/B RESULT")
    print("=" * 78)
    _report("10:30-13:00 (old)", old_result)
    _report(f"{new_start}-{new_end} (new)", new_result)

    print("\nVerdict:")
    if new_result["trades"] < 5:
        print("  ⚪ Too few trades in the new variant to trust — do not ship yet.")
    else:
        old_exp = (old_result["pnl"] / old_result["trades"]) if old_result["trades"] else 0.0
        new_exp = (new_result["pnl"] / new_result["trades"]) if new_result["trades"] else 0.0
        if new_exp > old_exp and new_exp > 0:
            print(f"  🟢 Improved (${old_exp:+.2f} -> ${new_exp:+.2f}/trade) and positive — ship it.")
        elif new_exp > old_exp:
            print(f"  🟡 Improved (${old_exp:+.2f} -> ${new_exp:+.2f}/trade) but still negative — do not ship.")
        else:
            print(f"  🔴 No improvement (${old_exp:+.2f} -> ${new_exp:+.2f}/trade). Do not ship.")

    print("\nLive bot behavior is unchanged by this script (flag restored).")


if __name__ == "__main__":
    main()

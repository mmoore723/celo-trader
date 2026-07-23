"""
diag_orb_replay.py — Replay INST_ORB's exact live logic against today's real
SPY (or any ticker) bars, with full gate-by-gate logging turned on.

This exists because a screenshot of a third-party TradingView indicator
claiming SPY "should have printed" doesn't tell us whether OUR bot's
specific gates (retest tolerance, RVOL threshold, VWAP-drift dead-cat-bounce
check, overextension cutoff) blocked a real setup, or whether there wasn't
a comparable setup for OUR strategy in the first place. Two different tools
looking at "ORB" are not automatically looking at the same thing — different
opening-range window, different retest requirements, different session/
timezone. This replays our own code against our own real bars so the answer
is grounded in what our bot actually saw, not a comparison to an unrelated
indicator.

Uses the EXACT same indicator-frame builder and evaluate() function the live
router calls — no logic is reimplemented or approximated here.

Usage:
    python3 diag_orb_replay.py            # SPY, most recently completed session
    python3 diag_orb_replay.py QQQ
"""

from __future__ import annotations

import logging
import sys

from broker import AlpacaClient
from signals import bars_to_df, get_opening_range
from strategy_router import _build_indicator_frame
from strategies import inst_orb

# Surface every INFO/DEBUG line inst_orb.py already logs internally —
# breakout detection, retest touch, bounce confirm/fail, every gate reject.
logging.basicConfig(level=logging.DEBUG, format="%(message)s", stream=sys.stdout)
logging.getLogger("celo_trader.strategies.inst_orb").setLevel(logging.DEBUG)
logging.getLogger("celo_trader.signals").setLevel(logging.WARNING)   # quiet noise


def main() -> None:
    ticker = sys.argv[1].upper() if len(sys.argv) > 1 else "SPY"
    alpaca = AlpacaClient()

    bars, is_error, is_live = alpaca.get_session_bars(ticker, "5Min")
    if is_error or not bars:
        print(f"Could not fetch 5-min session bars for {ticker}.")
        return

    df = bars_to_df(bars)
    if df.empty:
        print(f"No bars returned for {ticker}.")
        return

    session_date = df["time"].iloc[-1].date()
    print("=" * 90)
    print(f"INST_ORB REPLAY — {ticker} — session {session_date} "
          f"({'still live' if is_live else 'completed'})")
    print("=" * 90)

    today = _build_indicator_frame(df)
    if today.empty:
        print("Indicator frame came back empty — not enough bars.")
        return

    or_data = get_opening_range(today)
    if or_data is None:
        print("No opening range could be computed (missing 09:30 bar?).")
    else:
        print(f"Opening range: HIGH={or_data.get('high'):.2f}  LOW={or_data.get('low'):.2f}\n")

    print("--- inst_orb.py internal gate log (breakout/retest/bounce/RVOL/VWAP) ---")
    result = inst_orb.evaluate(today, ticker=ticker)
    print("--- end gate log ---\n")

    if result is None:
        print(f"RESULT: No INST_ORB signal fired for {ticker} today.")
        print("Read the gate log above for the specific reason — it will be one of:")
        print("  - no breakout ever closed outside the OR (state stayed 'idle')")
        print("  - breakout seen but retest never touched the boundary within tolerance")
        print("  - retest touched but bounce never confirmed (closed back through)")
        print("  - bounce confirmed but blocked by: cooldown / overextension (>3 ATR) /")
        print("    RVOL threshold / VWAP-drift dead-cat-bounce check")
    else:
        print(f"RESULT: INST_ORB DID fire — direction={result.direction} "
              f"confidence={result.confidence:.2f} rvol={result.rvol:.2f} "
              f"trigger_bar={result.trigger_bar}")
        print(f"meta: {result.meta}")


if __name__ == "__main__":
    main()

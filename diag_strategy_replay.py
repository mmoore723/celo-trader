"""
diag_strategy_replay.py — Replay EVERY active strategy's real evaluate()
logic bar-by-bar against a ticker's actual session bars, with full gate
logging on, to answer "should something have fired here?" with evidence
instead of eyeballing a chart.

Why bar-by-bar: the live bot calls each strategy's evaluate(today, ticker)
once per real-time tick, where `today` is every bar so far that day. Most
strategies only look at the LAST row of `today` (a fresh decision each tick).
Calling evaluate() once with the whole day's data is NOT equivalent to how
the bot actually ran — it would only reflect what the LAST bar of the day
looked like. This replays it exactly like the live loop does: growing the
slice one bar at a time and re-evaluating every strategy at every bar.

INST_ORB is the one exception — its retest state machine already replays
the full slice internally on every call by design (see its own docstring),
so it only needs to be called once with the complete day.

This uses the ACTUAL strategy modules — nothing here is reimplemented or
approximated. If a strategy doesn't fire, the DEBUG-level log lines already
written into that strategy's evaluate() function will say exactly which
gate blocked it (RVOL, structure confirmation, VWAP alignment, etc.).

Usage:
    python3 diag_strategy_replay.py            # SPY, most recent session
    python3 diag_strategy_replay.py QQQ
    python3 diag_strategy_replay.py SPY MID_BRK TREND_CONT   # only these
"""

from __future__ import annotations

import logging
import sys

from broker import AlpacaClient
from signals import bars_to_df
from strategy_router import _build_indicator_frame
from strategies import inst_orb, vwap_pb, fvg, ifvg, mid_brk, aft_rev, trend_cont

logging.basicConfig(level=logging.DEBUG, format="%(message)s", stream=sys.stdout)
for _name in ("signals", "database", "urllib3", "broker"):
    logging.getLogger(f"celo_trader.{_name}").setLevel(logging.WARNING)

_STRATEGIES = {
    "INST_ORB":   inst_orb.evaluate,
    "VWAP_PB":    vwap_pb.evaluate,
    "FVG":        fvg.evaluate,
    "IFVG":       ifvg.evaluate,
    "MID_BRK":    mid_brk.evaluate,
    "AFT_REV":    aft_rev.evaluate,
    "TREND_CONT": trend_cont.evaluate,
}

# INST_ORB replays the whole day internally on a single call — see its
# module docstring. Everything else must be fed a growing bar-by-bar slice
# to match how the live bot actually calls it (once per real-time tick).
_FULL_DAY_REPLAY = {"INST_ORB"}


def main() -> None:
    args = [a.upper() for a in sys.argv[1:]]
    if args and args[0] in _STRATEGIES:
        # First arg is a strategy name, not a ticker — default ticker to SPY.
        ticker    = "SPY"
        requested = args
    else:
        ticker    = args[0] if args else "SPY"
        requested = args[1:] if len(args) > 1 else list(_STRATEGIES.keys())

    for name in list(_STRATEGIES):
        logging.getLogger(f"celo_trader.strategies.{name.lower()}").setLevel(logging.DEBUG)

    alpaca = AlpacaClient()
    bars, is_error, is_live = alpaca.get_session_bars(ticker, "5Min")
    if is_error or not bars:
        print(f"Could not fetch 5-min session bars for {ticker}.")
        return

    df = bars_to_df(bars)
    if df.empty:
        print(f"No bars returned for {ticker}.")
        return

    today = _build_indicator_frame(df)
    if today.empty:
        print("Indicator frame came back empty — not enough bars.")
        return

    session_date = df["time"].iloc[-1].date()
    print("=" * 100)
    print(f"STRATEGY REPLAY — {ticker} — session {session_date} — "
          f"strategies: {', '.join(requested)}")
    print("=" * 100)

    found: list[tuple] = []

    for name in requested:
        fn = _STRATEGIES.get(name)
        if fn is None:
            print(f"  (skip — unknown strategy '{name}')")
            continue

        print(f"\n--- {name} gate log ---")
        if name in _FULL_DAY_REPLAY:
            sig = fn(today, ticker=ticker)
            if sig is not None:
                found.append((today["time"].iloc[-1], name, sig))
        else:
            min_len = 20 if name == "TREND_CONT" else 10
            for i in range(min_len, len(today)):
                slice_df = today.iloc[: i + 1].reset_index(drop=True)
                try:
                    sig = fn(slice_df, ticker=ticker)
                except Exception as e:
                    print(f"  [{name}] raised {type(e).__name__}: {e} at bar {slice_df['time'].iloc[-1]}")
                    continue
                if sig is not None:
                    found.append((slice_df["time"].iloc[-1], name, sig))
        print(f"--- end {name} gate log ---")

    print("\n" + "=" * 100)
    print("RAW SIGNALS FOUND (pre-router-gates — confidence floor, conflict veto,")
    print("regime gate, ADX gate, session bias etc. still apply downstream and")
    print("could still block these; this shows only whether the strategy's own")
    print("entry conditions were structurally satisfied at that bar)")
    print("=" * 100)
    if not found:
        print("None. No strategy's raw entry conditions were satisfied at any bar today.")
        print("Read the gate logs above — every rejection reason is logged at DEBUG level.")
    else:
        for bar_time, name, sig in found:
            print(f"  {bar_time}  {name:<11} direction={sig.direction:<8} "
                  f"confidence={sig.confidence:.2f} rvol={sig.rvol:.2f}")


if __name__ == "__main__":
    main()

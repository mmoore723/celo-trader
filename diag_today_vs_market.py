"""
diag_today_vs_market.py — Audit today's trades against what the underlying
market actually did, not just the bot's own P&L numbers.

The DB tells you entry/exit price and P&L. It does NOT tell you:
  - whether the entry was a CHASE (price already extended away from VWAP
    before the bot got in)
  - whether the exit was RIGHT (price kept moving against us afterward —
    good exit) or LEFT MONEY ON THE TABLE (price kept moving in our favor
    after we exited — exit was too early/too tight)

This pulls each ticker's real 1-min underlying bars for today (Alpaca) and
lines them up against every trade entered today, live or paper, open or
closed. Real bars, real trade rows — nothing here is estimated or guessed.

Usage:
    python3 diag_today_vs_market.py            # today, ET
    python3 diag_today_vs_market.py 2026-07-16 # specific date (must be
                                                # recent enough that Alpaca
                                                # still serves the session)
"""

from __future__ import annotations

import sys
from datetime import datetime, date as _date

import pandas as pd

from database import get_conn
from broker import AlpacaClient
from signals import bars_to_df, compute_vwap

POST_EXIT_WINDOW_MIN = 15   # how far past the exit to look for "left on the table"
CHASE_LOOKBACK_MIN   = 10   # how far before entry to measure "already extended"


def _parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s)


def _nearest_bar_idx(df: pd.DataFrame, ts: datetime) -> int | None:
    """Index of the bar whose time is closest to (and not after) ts."""
    if df.empty:
        return None
    mask = df["time"] <= ts
    if not mask.any():
        return 0
    return int(df[mask].index[-1])


def main() -> None:
    target_date = (
        _date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else datetime.now().date()
    )

    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, ticker, strategy_id, option_type, entry_price, exit_price,
                   entry_time, exit_time, status, exit_reason, realized_pnl,
                   peak_price, mae_price, contracts
            FROM trades
            WHERE date(entry_time) = ?
            ORDER BY entry_time
            """,
            (target_date.isoformat(),),
        ).fetchall()

    if not rows:
        print(f"No trades found with entry_time on {target_date.isoformat()}.")
        return

    tickers = sorted({r["ticker"] for r in rows})
    alpaca = AlpacaClient()
    bar_cache: dict[str, pd.DataFrame] = {}
    for t in tickers:
        bars, is_error, _ = alpaca.get_session_bars(t, "1Min")
        if is_error or not bars:
            print(f"  ⚠️  Could not fetch underlying bars for {t} — skipping market context for its trades.")
            bar_cache[t] = pd.DataFrame()
            continue
        df = bars_to_df(bars)
        df["vwap"] = compute_vwap(df)
        bar_cache[t] = df.reset_index(drop=True)

    print("=" * 130)
    print(f"TRADES vs MARKET — {target_date.isoformat()}  ({len(rows)} trade(s))")
    print("=" * 130)
    header = (f"{'TIME':<9} {'TICKER':<6} {'STRAT':<11} {'DIR':<7} {'HELD(m)':>7} "
              f"{'ENTRY$':>7} {'EXIT$':>7} {'P&L':>9} {'MFE%':>6} {'MAE%':>6}  "
              f"{'CHASE':>7} {'POST-EXIT':>10}  EXIT REASON")
    print(header)
    print("-" * 130)

    n_chase = 0
    n_left_on_table = 0
    n_good_exit = 0
    n_open = 0

    for r in rows:
        ticker    = r["ticker"]
        direction = "bullish" if (r["option_type"] or "call").lower() == "call" else "bearish"
        entry_t   = _parse_iso(r["entry_time"])
        is_open   = r["status"] == "open"
        exit_t    = _parse_iso(r["exit_time"]) if r["exit_time"] else None
        entry_p   = float(r["entry_price"])
        exit_p    = float(r["exit_price"]) if r["exit_price"] is not None else None
        peak_p    = float(r["peak_price"]) if r["peak_price"] is not None else entry_p
        mae_p     = float(r["mae_price"])  if r["mae_price"]  is not None else entry_p
        mfe_pct   = (peak_p - entry_p) / entry_p * 100 if entry_p else 0.0
        mae_pct   = (mae_p  - entry_p) / entry_p * 100 if entry_p else 0.0

        held_min = (
            ((exit_t or datetime.now()) - entry_t).total_seconds() / 60.0
        )

        df = bar_cache.get(ticker, pd.DataFrame())
        chase_desc = "n/a"
        post_desc  = "OPEN" if is_open else "n/a"

        if not df.empty:
            entry_idx = _nearest_bar_idx(df, entry_t)
            if entry_idx is not None and entry_idx > 0:
                # ── Chase check: how far has underlying already moved in the
                # trade's direction over the last CHASE_LOOKBACK_MIN minutes,
                # relative to VWAP at entry? Large same-direction extension
                # right before entry = buying the top of the move already.
                lookback_start = max(0, entry_idx - CHASE_LOOKBACK_MIN)
                seg = df.iloc[lookback_start:entry_idx + 1]
                if len(seg) >= 2:
                    move_pct = (seg["close"].iloc[-1] - seg["close"].iloc[0]) / seg["close"].iloc[0] * 100
                    signed_move = move_pct if direction == "bullish" else -move_pct
                    if signed_move > 0.15:
                        chase_desc = f"+{signed_move:.2f}%"
                        n_chase += 1
                    else:
                        chase_desc = f"{signed_move:+.2f}%"

            if exit_t is not None and not is_open:
                exit_idx = _nearest_bar_idx(df, exit_t)
                if exit_idx is not None:
                    post_end_idx = min(len(df) - 1, exit_idx + POST_EXIT_WINDOW_MIN)
                    if post_end_idx > exit_idx:
                        exit_underlying = float(df["close"].iloc[exit_idx])
                        post_underlying = float(df["close"].iloc[post_end_idx])
                        drift_pct = (post_underlying - exit_underlying) / exit_underlying * 100
                        signed_drift = drift_pct if direction == "bullish" else -drift_pct
                        if signed_drift > 0.10:
                            post_desc = f"LEFT +{signed_drift:.2f}%"
                            n_left_on_table += 1
                        elif signed_drift < -0.10:
                            post_desc = f"GOOD {signed_drift:+.2f}%"
                            n_good_exit += 1
                        else:
                            post_desc = f"flat {signed_drift:+.2f}%"
        if is_open:
            n_open += 1

        print(f"{entry_t.strftime('%H:%M:%S'):<9} {ticker:<6} {r['strategy_id']:<11} "
              f"{direction:<7} {held_min:>7.1f} {entry_p:>7.2f} "
              f"{(exit_p if exit_p is not None else 0):>7.2f} "
              f"{(r['realized_pnl'] or 0):>+9.2f} {mfe_pct:>6.1f} {mae_pct:>6.1f}  "
              f"{chase_desc:>7} {post_desc:>10}  {r['exit_reason'] or ('OPEN' if is_open else '')}")

    print("\n" + "=" * 130)
    print("SUMMARY")
    print("=" * 130)
    print(f"Total trades today:        {len(rows)}  ({n_open} still open)")
    print(f"Entries that CHASED (>0.15% same-direction move in the "
          f"{CHASE_LOOKBACK_MIN}min before entry): {n_chase}")
    print(f"Exits that LEFT MONEY ON THE TABLE (market kept moving our way "
          f"{POST_EXIT_WINDOW_MIN}min after exit): {n_left_on_table}")
    print(f"Exits that were GOOD (market reversed against us after exit):    {n_good_exit}")
    print("\nInterpretation guide:")
    print("  - High CHASE count concentrated in one strategy → that strategy's entry")
    print("    gate needs an 'already extended' check (distance from VWAP/EMA at entry).")
    print("  - High LEFT-ON-THE-TABLE count → stops/targets may be too tight for the")
    print("    volatility that ticker/strategy actually sees — consider loosening,")
    print("    but only after checking this isn't offset by MAE-side stopouts too.")
    print("  - High GOOD-EXIT count → exits are doing their job; don't touch them.")


if __name__ == "__main__":
    main()

"""
analyze_today_exits.py — Full-session read-only signal audit + P&L replay.

Two questions answered with real Alpaca bar data:

  A) For the 8 trades that were actually taken today (all 20-min timebox exits):
     what would the option have been worth if held 30 / 45 / 60 minutes instead?

  B) What ELSE did the strategy engine see today — across all 8 strategies and
     all 5 tickers in TICKER_UNIVERSE — that we didn't trade, and how much was
     left on the table by not taking those signals?

Why this matters: today's network failure knocked the bot offline 09:30–11:57,
so every trade entered 2+ hours late. The strategies that fire later in the day
(MID_BRK, AFT_REV, VWAP_PB, etc.) might have generated viable entries during
the hours the bot was recovering.  Separately, MAX_CONCURRENT_POSITIONS=2
forces signals to queue — signals fired while 2 positions were already open are
not executed even if the bot was online.  This script exposes both.

Must be run on a machine with real Alpaca network access (the Cowork sandbox
is allowlisted and cannot reach Alpaca's API endpoints).

Usage:
    python3 analyze_today_exits.py                    # today's session
    python3 analyze_today_exits.py --date 2026-06-22  # a specific day
    python3 analyze_today_exits.py --date 2026-06-22 --strategy INST_ORB

Output: signal timeline → Section A (actual trades, hold-longer analysis) →
Section B (missed signals, hypothetical P&L) → grand total.
Read-only — does not place orders, modify the DB, or touch trading_logic.py.
"""

import argparse
import math
import sqlite3
import sys
from datetime import datetime, timedelta

import pandas as pd

from broker import AlpacaClient
from signals import bars_to_df
from config import get_db_path, TICKER_UNIVERSE

# ── Monkeypatch kill-lock check BEFORE importing strategy_router ──────────────
# route_signals() reads bot_state.json's live kill-lock state, which may differ
# from what was true during today's session.  We want a clean replay; the kill
# lock should not have fired today (session P&L was -$25, well below the 10%
# hard cap on a $2,213 balance) but we patch it out explicitly so the replay is
# deterministic regardless of when this script is run.
import risk as _risk
_risk.check_kill_lock = lambda: (False, "")  # replay mode

from strategy_router import route_signals  # noqa: E402  (must come after patch)


# ═══════════════════════════════════════════════════════════════════════════════
# Black-Scholes helpers  (stable numerics — see fix notes below)
# ═══════════════════════════════════════════════════════════════════════════════

# FIX 2026-06-23 (applied from the first run of this script):
#   put formula via put-call parity is catastrophically unstable when the
#   underlying is far above the strike — large terms cancel into a tiny,
#   noise-dominated result.  Direct put formula + implied-vol bisection instead.

def _bs_price(S: float, K: float, now_dt: datetime, expiry_dt: datetime,
              is_call: bool, sigma: float = 0.16, r: float = 0.05) -> float:
    """Standard Black-Scholes with numerically-stable direct put formula."""
    try:
        T = max((expiry_dt - now_dt).total_seconds(), 60) / (365.0 * 24 * 3600)
        d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)

        def _N(x: float) -> float:
            return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

        disc = math.exp(-r * T)
        if is_call:
            px = S * _N(d1) - K * disc * _N(d2)
        else:
            px = K * disc * _N(-d2) - S * _N(-d1)   # direct/stable put formula
        return max(0.01, px)
    except Exception:
        return max(0.01, S * 0.013)


def _implied_vol(S: float, K: float, now_dt: datetime, expiry_dt: datetime,
                 is_call: bool, target_price: float, r: float = 0.05) -> float:
    """
    Bisection over sigma in [1%, 500%] to find the vol that reproduces the
    real entry fill.  Monotonic in vol → always converges, never blows up.
    """
    lo, hi = 0.01, 5.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if _bs_price(S, K, now_dt, expiry_dt, is_call, sigma=mid, r=r) < target_price:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _nearest_bar(df: pd.DataFrame, ts: datetime) -> "pd.Series | None":
    """Last bar at-or-before ts — never looks into the future."""
    eligible = df[df["time"] <= ts]
    return eligible.iloc[-1] if not eligible.empty else None


# ═══════════════════════════════════════════════════════════════════════════════
# Signal replay helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _direction_to_option_type(direction: str) -> str:
    """'bullish' → 'call', 'bearish' → 'put'."""
    return "call" if direction == "bullish" else "put"


def positions_open_at(all_trades: list[dict], ts: pd.Timestamp) -> list[dict]:
    """
    Return all trades whose window (entry_time, exit_time] straddles ts.
    Uses ALL trades for the day (open + closed), not just closed ones.
    """
    open_ones = []
    for t in all_trades:
        e = pd.to_datetime(t["entry_time"])
        x = pd.to_datetime(t["exit_time"]) if t.get("exit_time") else None
        if e <= ts and (x is None or x > ts):
            open_ones.append(t)
    return open_ones


def _atm_strike(underlying: float, is_call: bool, ticker: str) -> float:
    """
    Near-ATM strike for a hypothetical (never-entered) option.
    ETFs: $1 steps.  Stocks: $2.50 steps.
    Calls: slightly OTM (round up).  Puts: slightly OTM (round down).
    """
    step = 1.0 if ticker in ("SPY", "QQQ") else 2.5
    raw = (math.ceil(underlying / step) * step if is_call
           else math.floor(underlying / step) * step)
    return round(raw, 2)


# Default annualized implied vol by ticker, used when no real trade exists
# on that ticker today to calibrate against.  Sourced from recent realized
# vol ranges; conservative mid-range estimates.
_DEFAULT_IV: dict[str, float] = {
    "SPY":  0.15,
    "QQQ":  0.18,
    "AAPL": 0.25,
    "NVDA": 0.40,
    "TSLA": 0.50,
}


def replay_all_signals(
    ac: AlpacaClient,
    session_date: str,
) -> tuple[dict[str, pd.DataFrame], list[dict]]:
    """
    Fetch 1-min session bars + 5-min historical bars for each ticker in
    TICKER_UNIVERSE, run route_signals() on each (all 8 strategies enabled),
    and return all signals that fired today sorted by trigger time.

    Returns:
        bars_by_ticker : {ticker: df_1m_today}  for P&L checkpoint lookups
        all_signals    : list of signal dicts  (sorted by trigger_bar ascending)
    """
    bars_by_ticker: dict[str, pd.DataFrame] = {}
    all_signals: list[dict] = []

    for ticker in TICKER_UNIVERSE:
        # ── Today's 1-min bars (used for strategy replay + P&L checkpoints) ──
        raw_1m, is_err, _ = ac.get_session_bars(ticker, "1Min")
        if is_err or not raw_1m:
            print(f"  ⚠️  Cannot fetch 1-min bars for {ticker} — skipping.")
            continue
        df_1m = bars_to_df(raw_1m)

        # Filter strictly to the session_date (get_session_bars returns
        # the most recent session; on a same-day run this is today's bars).
        df_today = df_1m[df_1m["time"].dt.date.astype(str) == session_date].copy()
        if df_today.empty:
            print(f"  ⚠️  No bars for {ticker} on {session_date} "
                  f"(most recent bars are from "
                  f"{df_1m['time'].dt.date.max()}).")
            continue

        bars_by_ticker[ticker] = df_today.reset_index(drop=True)

        # ── 5-min historical bars for 10-day RVOL (prior sessions only) ──────
        hist_5m, hist_err = ac.get_bars(ticker, "5Min", limit=1500)
        if not hist_err and hist_5m:
            df_hist = bars_to_df(hist_5m)
            # Exclude today's date so we don't mix timeframes mid-session.
            df_hist = df_hist[df_hist["time"].dt.date.astype(str) < session_date]
            df_aug = (pd.concat([df_hist, df_today], ignore_index=True)
                      .sort_values("time").reset_index(drop=True))
        else:
            df_aug = df_today.copy()

        # ── Replay all 8 strategies ──────────────────────────────────────────
        sigs = route_signals(df_aug, ticker, enabled_strategies=None)
        for sig in sigs:
            all_signals.append({
                "ticker":      ticker,
                "strategy_id": sig.strategy_id,
                "direction":   sig.direction,
                "option_type": _direction_to_option_type(sig.direction),
                "confidence":  sig.confidence,
                "rvol":        sig.rvol,
                "trigger_bar": pd.to_datetime(sig.trigger_bar),
            })

    all_signals.sort(key=lambda s: s["trigger_bar"])
    return bars_by_ticker, all_signals


# ═══════════════════════════════════════════════════════════════════════════════
# P&L modelling helpers
# ═══════════════════════════════════════════════════════════════════════════════

def model_checkpoints(
    df_1m: pd.DataFrame,
    entry_dt: pd.Timestamp,
    expiry_dt: datetime,
    is_call: bool,
    strike: float,
    entry_option_px: float,
    implied_sigma: float,
    checkpoints_min: list[int],
) -> dict[int, float]:
    """
    For each checkpoint (minutes after entry), compute the modelled option price
    and the resulting P&L vs entry (×100 multiplier, 1 contract).
    """
    results = {}
    for mins in checkpoints_min:
        cp_dt = entry_dt + timedelta(minutes=mins)
        bar = _nearest_bar(df_1m, cp_dt)
        if bar is None:
            continue
        SN = float(bar["close"])
        bsN = _bs_price(SN, strike, cp_dt.to_pydatetime(), expiry_dt,
                        is_call, sigma=implied_sigma)
        results[mins] = (bsN - entry_option_px) * 100
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# main
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"),
                    help="Session date YYYY-MM-DD (default: today)")
    ap.add_argument("--strategy", default=None,
                    help="Restrict DB trade query to one strategy_id")
    args = ap.parse_args()

    EXPIRY_DATE = "2026-06-29"   # today's actual contracts — update if re-running later
    expiry_dt   = datetime.strptime(EXPIRY_DATE, "%Y-%m-%d").replace(hour=16, minute=0)
    CHECKPOINTS = [20, 30, 45, 60]

    # ── 1. Pull actual closed trades from the DB ──────────────────────────────
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row

    # Full-day trades (all statuses) for concurrent-position reconstruction
    all_db_trades = [dict(r) for r in conn.execute(
        "SELECT * FROM trades WHERE entry_time LIKE ? ORDER BY entry_time",
        [f"{args.date}%"],
    ).fetchall()]

    # Closed trades for the hold-longer analysis (optionally filtered by strategy)
    q = "SELECT * FROM trades WHERE entry_time LIKE ? AND status='closed'"
    params: list = [f"{args.date}%"]
    if args.strategy:
        q += " AND strategy_id=?"
        params.append(args.strategy)
    q += " ORDER BY entry_time"
    closed_trades = [dict(r) for r in conn.execute(q, params).fetchall()]
    conn.close()

    if not all_db_trades:
        print(f"No trades in DB for {args.date}.")
        sys.exit(0)

    print(f"\n{'═'*72}")
    print(f"  CELO TRADER — Full Session Audit  ({args.date})")
    print(f"{'═'*72}\n")
    print(f"DB: {len(all_db_trades)} total trade(s) today, "
          f"{len(closed_trades)} closed.\n")

    # ── 2. Signal replay across all 5 tickers, all 8 strategies ──────────────
    print("Replaying all 8 strategies across TICKER_UNIVERSE…  (this fetches Alpaca bars)")
    ac = AlpacaClient()
    bars_by_ticker, all_signals = replay_all_signals(ac, args.date)

    if not bars_by_ticker:
        print("\n⚠️  Could not fetch any bars — aborting.")
        sys.exit(1)

    # Per-ticker implied-vol from actual trades (for hypothetical pricing)
    ticker_iv: dict[str, list[float]] = {}
    for t in closed_trades:
        tk = t["ticker"]
        df = bars_by_ticker.get(tk)
        if df is None:
            continue
        entry_dt = pd.to_datetime(t["entry_time"])
        bar0 = _nearest_bar(df, entry_dt)
        if bar0 is None:
            continue
        S0 = float(bar0["close"])
        is_call = (t["option_type"] or "").lower() == "call"
        iv = _implied_vol(S0, float(t["strike"]), entry_dt.to_pydatetime(),
                          expiry_dt, is_call, float(t["entry_price"]))
        ticker_iv.setdefault(tk, []).append(iv)
    # Average IVs per ticker (will be used for missed-signal pricing)
    avg_iv: dict[str, float] = {
        tk: sum(ivs) / len(ivs) for tk, ivs in ticker_iv.items()
    }

    # ── 3. Match signals to actual trades & classify ──────────────────────────
    matched_trade_ids: set[int] = set()
    orb_taken_tickers: set[str] = set()   # tickers where INST_ORB was actually traded

    signal_rows: list[dict] = []
    for sig in all_signals:
        tk         = sig["ticker"]
        strategy   = sig["strategy_id"]
        direction  = sig["direction"]
        opt_type   = sig["option_type"]
        trigger_ts = sig["trigger_bar"]

        # Try to match to a real trade (same ticker + strategy + direction)
        match: "dict | None" = None
        for t in closed_trades:
            if (t["id"] not in matched_trade_ids
                    and t["ticker"] == tk
                    and t["strategy_id"] == strategy
                    and (t["option_type"] or "").lower() == opt_type):
                match = t
                matched_trade_ids.add(t["id"])
                if strategy == "INST_ORB":
                    orb_taken_tickers.add(tk)
                break

        # Determine why the signal was (or wasn't) traded
        open_at_trigger = positions_open_at(all_db_trades, trigger_ts)
        n_open = len(open_at_trigger)

        if match:
            delay_min = (pd.to_datetime(match["entry_time"]) - trigger_ts).total_seconds() / 60
            status = (f"TAKEN  → Trade #{match['id']}  "
                      f"P&L ${float(match['realized_pnl']):+.2f}"
                      + (f"  (entry {delay_min:+.0f}min late — network delay)"
                         if delay_min > 5 else ""))
        elif strategy == "INST_ORB" and tk in orb_taken_tickers:
            status = "BLOCKED — ORB already triggered for this ticker today"
        elif n_open >= 2:
            tickers_open = ", ".join(t["ticker"] for t in open_at_trigger)
            status = f"BLOCKED — {n_open} positions open ({tickers_open})"
        else:
            status = f"MISSED  ← viable  ({n_open} position(s) open at trigger)"

        signal_rows.append({
            **sig,
            "match":      match,
            "n_open":     n_open,
            "status":     status,
            "is_viable":  (match is None
                           and strategy != "INST_ORB" or tk not in orb_taken_tickers
                           and n_open < 2),
        })

    # ── 4. Print signal timeline ──────────────────────────────────────────────
    print(f"\n{'─'*72}")
    print("  SIGNAL TIMELINE — Every Strategy Signal Fired Today")
    print(f"{'─'*72}")
    if not all_signals:
        print("  (no signals fired — check that bars were fetched correctly)")
    for row in signal_rows:
        t_str = row["trigger_bar"].strftime("%H:%M")
        print(f"  {t_str}  {row['ticker']:<5}  {row['strategy_id']:<10}  "
              f"{row['direction']:<8}  conf={row['confidence']:.2f}  "
              f"rvol={row['rvol']:.1f}x")
        print(f"         → {row['status']}")
    print()

    # ── SECTION A: Actual trades — hold-longer analysis ───────────────────────
    print(f"\n{'═'*72}")
    print("  SECTION A: Actual Trades — What If We'd Held Longer?")
    print(f"{'═'*72}")

    totals_actual: dict[int, float] = {m: 0.0 for m in CHECKPOINTS}
    actual_total_pnl = 0.0

    for t in closed_trades:
        tk = t["ticker"]
        df = bars_by_ticker.get(tk)
        if df is None:
            print(f"\n  ⚠️  Trade #{t['id']} ({tk}): no bar data — skipping.")
            continue

        entry_dt    = pd.to_datetime(t["entry_time"])
        exit_dt_raw = pd.to_datetime(t["exit_time"]) if t.get("exit_time") else None
        is_call     = (t["option_type"] or "").lower() == "call"
        strike      = float(t["strike"])
        entry_px    = float(t["entry_price"])
        actual_pnl  = float(t["realized_pnl"])
        actual_total_pnl += actual_pnl

        bar0 = _nearest_bar(df, entry_dt)
        if bar0 is None:
            print(f"\n  ⚠️  Trade #{t['id']} ({tk}): no bar at entry time — skipping.")
            continue
        S0 = float(bar0["close"])
        iv = _implied_vol(S0, strike, entry_dt.to_pydatetime(), expiry_dt,
                          is_call, entry_px)

        print(f"\n  Trade #{t['id']} — {tk} {t['option_type'].upper()} ${strike:.0f} "
              f"expiry={EXPIRY_DATE}  strategy={t['strategy_id']}")
        print(f"    Entry  {entry_dt.strftime('%H:%M:%S')}  "
              f"underlying ${S0:.2f}  option ${entry_px:.2f}  "
              f"implied vol {iv:.0%}")
        print(f"    ACTUAL {exit_dt_raw.strftime('%H:%M:%S') if exit_dt_raw else '—'}  "
              f"({t['exit_reason']})  exit ${t['exit_price']:.2f}  "
              f"P&L ${actual_pnl:+.2f}")

        cp_pnls = model_checkpoints(df, entry_dt, expiry_dt, is_call,
                                    strike, entry_px, iv, CHECKPOINTS)
        for mins, pnl in cp_pnls.items():
            totals_actual[mins] += pnl
            tag = "  ← what actually happened" if mins == 20 else ""
            bar = _nearest_bar(df, entry_dt + timedelta(minutes=mins))
            s_str = f"${float(bar['close']):.2f}" if bar is not None else "n/a"
            print(f"    +{mins:>2}min  underlying {s_str:<10}  "
                  f"modelled P&L ${pnl:+.2f}{tag}")

    print(f"\n{'─'*72}")
    print(f"  ACTUAL total P&L today (20-min timebox):  ${actual_total_pnl:+.2f}")
    for mins in CHECKPOINTS:
        delta = totals_actual[mins] - actual_total_pnl
        print(f"  If held to +{mins}min:  ${totals_actual[mins]:+.2f}  "
              f"({delta:+.2f} vs actual)")
    print(f"{'─'*72}")

    # ── SECTION B: Viable missed signals ─────────────────────────────────────
    viable_missed = [
        r for r in signal_rows
        if r["match"] is None
        and r["n_open"] < 2
        and not (r["strategy_id"] == "INST_ORB"
                 and r["ticker"] in orb_taken_tickers)
    ]

    print(f"\n{'═'*72}")
    print("  SECTION B: Viable Missed Signals — Hypothetical P&L")
    print(f"{'═'*72}")

    if not viable_missed:
        print("\n  No viable missed signals found — every qualified signal was taken "
              "or the concurrent-position cap explains all gaps.\n")
    else:
        totals_missed: dict[int, float] = {m: 0.0 for m in CHECKPOINTS}

        for row in viable_missed:
            tk        = row["ticker"]
            strategy  = row["strategy_id"]
            direction = row["direction"]
            is_call   = (direction == "bullish")
            trigger   = row["trigger_bar"]
            df        = bars_by_ticker.get(tk)

            if df is None:
                continue

            bar0 = _nearest_bar(df, trigger)
            if bar0 is None:
                print(f"\n  ⚠️  {tk} {strategy}: no bar at trigger time — skipping.")
                continue
            S0     = float(bar0["close"])
            strike = _atm_strike(S0, is_call, tk)
            iv     = avg_iv.get(tk, _DEFAULT_IV.get(tk, 0.30))
            entry_option_px = _bs_price(S0, strike, trigger.to_pydatetime(),
                                        expiry_dt, is_call, sigma=iv)

            print(f"\n  {trigger.strftime('%H:%M')}  {tk:<5}  {strategy:<10}  "
                  f"{direction:<8}  (conf={row['confidence']:.2f}  rvol={row['rvol']:.1f}x)")
            print(f"    Hypothetical entry:  underlying ${S0:.2f}  "
                  f"strike ${strike:.2f} {'CALL' if is_call else 'PUT'}  "
                  f"IV {iv:.0%}  modelled premium ${entry_option_px:.2f}")
            print(f"    Reason not taken:    {row['status']}")

            cp_pnls = model_checkpoints(df, trigger, expiry_dt, is_call,
                                        strike, entry_option_px, iv, CHECKPOINTS)
            for mins, pnl in cp_pnls.items():
                totals_missed[mins] += pnl
                bar = _nearest_bar(df, trigger + timedelta(minutes=mins))
                s_str = f"${float(bar['close']):.2f}" if bar is not None else "n/a"
                print(f"    +{mins:>2}min  underlying {s_str:<10}  "
                      f"modelled P&L ${pnl:+.2f}")

        print(f"\n{'─'*72}")
        print(f"  Viable missed signals sub-total (hypothetical):")
        for mins in CHECKPOINTS:
            print(f"    +{mins}min:  ${totals_missed[mins]:+.2f}")

    # ── Grand total ───────────────────────────────────────────────────────────
    print(f"\n{'═'*72}")
    print("  GRAND TOTAL")
    print(f"{'═'*72}")
    print(f"  Actual trades only (20-min timebox):            ${actual_total_pnl:+.2f}")
    if viable_missed:
        for mins in CHECKPOINTS:
            combo = totals_actual[mins] + totals_missed[mins]
            print(f"  If actual held +{mins}min + missed signals taken:  ${combo:+.2f}")
    else:
        for mins in CHECKPOINTS:
            print(f"  If actual held +{mins}min (no missed signals):     "
                  f"${totals_actual[mins]:+.2f}")
    print(f"{'═'*72}")

    print("""
Caveats:
  - All option prices are MODELLED (Black-Scholes).  For actual trades,
    the model is calibrated to the real entry fill; for missed signals it
    uses average implied vol from today's same-ticker fills, or a ticker
    default if none exist.  Real bid/ask spread is not captured — treat
    these as directional estimates, not guaranteed fills.
  - "Viable missed" means ≤1 open position at trigger time AND not blocked
    by the per-ticker ORB-already-triggered guard.  Whether the bot would
    have picked THAT specific signal over a concurrent one on another ticker
    isn't modelled.
  - Network outage 09:30–11:57 ET today caused all 8 INST_ORB entries to
    be delayed ~2h.  Signals fired during that window have the trigger time
    of the actual breakout bar, but the "TAKEN" note shows real entry time.
  - Uses Alpaca IEX free-tier 1-min bars — same feed the bot uses live.
""")


if __name__ == "__main__":
    main()

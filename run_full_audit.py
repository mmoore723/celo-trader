"""
run_full_audit.py — ONE script for the whole real-data audit.

Why this exists (2026-07-20): audit_strategies.py, diag_strategy_features.py,
and diag_risk_math.py each independently called Backtester(ticker, months)
and re-fetched + re-replayed the SAME months of bars for the SAME tickers,
just to look at different slices of the same result. A single
Backtester.run() call already returns everything all three needed —
bt.trades has every strategy's full per-trade detail (P&L, exit_reason,
held_minutes, entry_rvol, entry_confidence, entry_meta). This script fetches
and replays ONCE per ticker and derives all three views from that one pass:

  1. Per-strategy expectancy/win-rate table      (was audit_strategies.py)
  2. Per-strategy risk math: realized win:loss,
     exit-reason mix, held-time on stop-type exits (was diag_risk_math.py)
  3. Win-vs-loss feature-gap table, automatically
     for EVERY strategy with enough trades        (was diag_strategy_features.py,
                                                     one strategy at a time)

One thing does NOT merge in: the raw ADX-signal funnel (what got blocked
BEFORE becoming a trade — diag_mid_brk_adx_funnel.py's job) needs a
different kind of scan that Backtester doesn't expose internally. That
stays available here as an optional flag (--adx-funnel STRATEGY_ID) so it's
still one script, just an extra pass only when you actually need it.

Every run also writes a timestamped report file to audit_reports/ so you
have one thing to look at (or paste back) instead of scrollback.

Usage:
    python3 run_full_audit.py                                    # 2mo, default tickers
    python3 run_full_audit.py 2 SPY QQQ NVDA AAPL TSLA AMD META AMZN MSFT GOOGL NFLX AVGO
    python3 run_full_audit.py 2 SPY QQQ NVDA --adx-funnel MID_BRK  # + raw signal funnel for one strategy
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, date
from pathlib import Path

from broker import AlpacaClient
from backtester import Backtester

DEFAULT_TICKERS   = ["SPY", "QQQ", "NVDA", "AAPL", "TSLA", "AMD", "META", "AMZN", "MSFT", "GOOGL"]
DEFAULT_MONTHS    = 2
MIN_TRADES_FOR_FEATURES = 5   # below this, a feature-gap comparison is just noise

# BUG FIX 2026-07-21 (real incident, not theoretical): the first parallel run
# used min(len(tickers), cpu_count()) = 8 workers on a MacBook Air. SPY, which
# took 1631s running alone, took 5694s (3.5x slower) under 8-way contention —
# 8 heavy pandas/numpy processes fighting over ~4 real performance cores on a
# fanless laptop. The machine died (almost certainly thermal/battery, running
# unplugged) partway through, losing ~2 hours of work with nothing recovered
# because results only got aggregated at the very end. Two fixes below:
# a much more conservative default worker count, and a per-ticker disk cache
# so a crash never loses completed tickers again. Override with AUDIT_WORKERS
# if you're on a desktop/plugged-in machine that can actually take more.
DEFAULT_WORKERS = 2

_CACHE_DIR = Path("audit_reports") / "_cache"


def _cache_path(ticker: str, months: int) -> Path:
    return _CACHE_DIR / f"{ticker}_{months}mo.json"


def _json_default(o):
    # numpy scalars (np.float64 etc.) show up in results via pandas/numpy
    # math and aren't natively JSON-serializable — coerce via .item() if
    # available, else fall back to str() so caching never hard-crashes.
    if hasattr(o, "item"):
        return o.item()
    return str(o)


def _load_cached(ticker: str, months: int) -> "dict | None":
    """
    Same-day cache hit only — a corrected backtest run earlier today is still
    valid to reuse; results from a prior day are stale (new trading day of
    data available) and should be recomputed, not silently reused.
    """
    path = _cache_path(ticker, months)
    if not path.exists():
        return None
    try:
        with open(path) as f:
            cached = json.load(f)
        if cached.get("_cached_date") != date.today().isoformat():
            return None
        return cached
    except Exception:
        return None


def _save_cache(ticker: str, months: int, result: dict) -> None:
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        to_write = dict(result)
        to_write["_cached_date"] = date.today().isoformat()
        with open(_cache_path(ticker, months), "w") as f:
            json.dump(to_write, f, default=_json_default)
    except Exception as ex:
        print(f"   (cache write failed for {ticker}, non-fatal: {ex})")


def _run_one_ticker(ticker: str, months: int) -> dict:
    """
    Runs inside a worker process — imports + constructs its own AlpacaClient
    rather than receiving one from the parent, since client objects (open
    HTTP sessions etc.) aren't reliably picklable across the process boundary.
    """
    from broker import AlpacaClient as _AC
    from backtester import Backtester as _BT
    alpaca = _AC()
    bt = _BT(alpaca, ticker, months=months, starting_capital=5000.0, direction="both")
    t0 = time.monotonic()
    result = bt.run()
    result["_elapsed"] = time.monotonic() - t0
    return result

_STRAT_NAMES = {
    "INST_ORB":   "Opening Range Breakout",
    "VWAP_PB":    "VWAP Pullback",
    "FVG":        "Fair Value Gap",
    "IFVG":       "Inverted Fair Value Gap",
    "MID_BRK":    "Mid-Day Breakdown",
    "AFT_REV":    "Afternoon Reversal",
    "TREND_CONT": "Trend Continuation",
    "CHAN_BREAK": "Channel Breakout",
    "BOS_MSS":    "Break of Structure",
}


class _Tee:
    """Writes to both stdout and the report file at once, no buffering surprises."""
    def __init__(self, *streams):
        self.streams = streams

    def write(self, s: str) -> None:
        for st in self.streams:
            st.write(s)

    def flush(self) -> None:
        for st in self.streams:
            st.flush()


def _fmt_elapsed(t0: float) -> str:
    return f"{time.monotonic() - t0:.0f}s"


def main() -> None:
    months  = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else DEFAULT_MONTHS
    args    = sys.argv[2:] if len(sys.argv) > 1 and sys.argv[1].isdigit() else sys.argv[1:]

    adx_funnel_strategy = None
    if "--adx-funnel" in args:
        idx = args.index("--adx-funnel")
        adx_funnel_strategy = args[idx + 1].upper()
        args = args[:idx] + args[idx + 2:]

    tickers = [a.upper() for a in args] or DEFAULT_TICKERS

    reports_dir = Path("audit_reports")
    reports_dir.mkdir(exist_ok=True)
    report_path = reports_dir / f"audit_{datetime.now().strftime('%Y-%m-%d_%H%M')}.txt"

    with open(report_path, "w") as report_file:
        out = _Tee(sys.stdout, report_file)
        _run(months, tickers, adx_funnel_strategy, out)

    print(f"\n📄 Full report saved to: {report_path}")


def _run(months: int, tickers: list[str], adx_funnel_strategy: "str | None", out) -> None:
    # alpaca is still constructed here for the optional --adx-funnel pass
    # below, which runs in the main process after the parallel tickers finish.
    alpaca = AlpacaClient()
    t_start = time.monotonic()

    n_workers = min(len(tickers), int(os.environ.get("AUDIT_WORKERS", DEFAULT_WORKERS)) or 1)
    print(f"RUN FULL AUDIT — {months} month(s), {len(tickers)} ticker(s): {', '.join(tickers)}",
          file=out, flush=True)

    # ── Same-day cache — reuse tickers already computed today instead of
    # re-paying the ~25-95min-per-ticker cost (2026-07-21, added after a run
    # crashed 2hrs in and lost 4 already-completed tickers' worth of work).
    to_run, cached_tickers = [], []
    results_by_ticker: dict = {}
    for t in tickers:
        c = _load_cached(t, months)
        if c is not None:
            results_by_ticker[t] = c
            cached_tickers.append(t)
        else:
            to_run.append(t)

    print(f"Started {datetime.now().strftime('%H:%M:%S')} — {n_workers} ticker(s) in parallel "
          f"(set AUDIT_WORKERS=N to change)", file=out, flush=True)
    if cached_tickers:
        print(f"  using today's cached results for: {', '.join(cached_tickers)} "
              f"(delete audit_reports/_cache/ to force a fresh run)", file=out, flush=True)
    print("", file=out, flush=True)

    # ── SINGLE fetch + replay pass per ticker, run concurrently ──────────────
    all_trades: list[dict] = []
    per_ticker_summary: list[str] = []
    # 2026-07-21: aggregate the entry-gate funnel across tickers so "why are
    # there so few trades" has a real, numeric answer instead of a guess.
    funnel: dict = defaultdict(int)

    if to_run:
        with ProcessPoolExecutor(max_workers=n_workers) as pool:
            futures = {pool.submit(_run_one_ticker, t, months): t for t in to_run}
            for fut in as_completed(futures):
                ticker = futures[fut]
                try:
                    result = fut.result()
                except Exception as _worker_ex:
                    print(f"   ❌ {ticker}: worker crashed — {_worker_ex}", file=out, flush=True)
                    continue
                results_by_ticker[ticker] = result
                _elapsed_str = f"{result.get('_elapsed', 0):.0f}s"
                if result.get("error"):
                    print(f"   ❌ {ticker} ({_elapsed_str}): {result['error']}", file=out, flush=True)
                else:
                    # Cache + print the one-line summary IMMEDIATELY, not after
                    # every ticker finishes — this is exactly the data that got
                    # lost in tonight's crash (4 tickers done, 0 recovered
                    # because the summary/cache only happened at the very end).
                    _save_cache(ticker, months, result)
                    dd_dollars = result.get("max_drawdown", 0)
                    print(f"   ✓ {ticker} done ({_elapsed_str}, total elapsed {_fmt_elapsed(t_start)}) — "
                          f"{result.get('total_trades', 0)} trades, "
                          f"return {result.get('total_return', 0):+.1f}%, "
                          f"win rate {result.get('win_rate', 0) * 100:.0f}%",
                          file=out, flush=True)

    # Rebuild per-ticker reporting in the original requested order (as_completed
    # finishes in whatever order the workers happen to complete, not input order).
    for ticker in tickers:
        result = results_by_ticker.get(ticker)
        if not result or result.get("error"):
            continue
        for t in result.get("trades", []):
            t = dict(t)
            t["ticker"] = ticker
            all_trades.append(t)
        _diag = result.get("diagnostics", {})
        for _k in ("total_bars", "trading_days", "raw_signals", "below_floor",
                   "conflict_veto", "chop_bars", "direction_skip", "no_contracts",
                   "rr_gate_blocked"):
            funnel[_k] += _diag.get(_k, 0)
        dd_dollars = result.get("max_drawdown", 0)
        per_ticker_summary.append(
            f"  {ticker}: {result.get('total_trades', 0)} trades, "
            f"return {result.get('total_return', 0):+.1f}%, "
            f"win rate {result.get('win_rate', 0) * 100:.0f}%, "
            f"max DD ${dd_dollars:.2f} ({dd_dollars/5000*100:.1f}%)  "
            f"({result.get('_elapsed', 0):.0f}s)"
        )

    print("\n" + "=" * 100, file=out)
    print("PER-TICKER SUMMARY", file=out)
    print("=" * 100, file=out)
    for line in per_ticker_summary:
        print(line, file=out)

    print("\n" + "=" * 100, file=out)
    print("ENTRY-GATE FUNNEL (aggregated across all tickers above)", file=out)
    print("=" * 100, file=out)
    _chop_pct = (funnel["chop_bars"] / funnel["total_bars"] * 100) if funnel["total_bars"] else 0.0
    print(
        f"  {funnel['total_bars']:>6} bars scanned across {funnel['trading_days']} trading days\n"
        f"  {funnel['chop_bars']:>6} of those ({_chop_pct:.1f}%) were in ADX<25 chop regime — "
        f"breakout strategies were never even evaluated on these bars (this is a coverage "
        f"gap, not a 'signals killed' count — those strategies might not have fired anyway)\n"
        f"  {funnel['raw_signals']:>6} bars had >=1 raw signal from any strategy (out of the "
        f"remaining non-chop bars, plus non-gated strategies during chop)\n"
        f"    -{funnel['below_floor']:>5} killed by the confidence floor "
        f"(< router's min confidence)\n"
        f"    -{funnel['conflict_veto']:>5} killed by the conflict veto "
        f"(2 strategies disagreed, too close to call)\n"
        f"    -{funnel['direction_skip']:>5} skipped by a calls-only/puts-only filter\n"
        f"    -{funnel['no_contracts']:>5} passed every gate but couldn't afford "
        f"even 1 contract\n"
        f"    -{funnel['rr_gate_blocked']:>5} passed every gate, affordable, but reward:risk "
        f"was below the 1.2x-1.6x minimum (2026-07-22 fidelity fix — live has always "
        f"enforced this, the backtester didn't until now)\n"
        f"  = {len(all_trades):>6} actual trades taken",
        file=out,
    )
    if funnel["raw_signals"] > 0:
        _survive_pct = len(all_trades) / funnel["raw_signals"] * 100
        print(
            f"  Signal survival rate: {_survive_pct:.1f}% of bars with a raw "
            f"signal became a real trade — the confidence floor is the dominant "
            f"filter if below_floor accounts for most of the gap.",
            file=out,
        )

    if not all_trades:
        print("\nNo trades in this window across any ticker — nothing further to report.", file=out)
        return

    # ── 1. Per-strategy expectancy table ────────────────────────────────────
    _print_expectancy_table(all_trades, out)

    # ── 2. Per-strategy risk math (win:loss, exit-reason mix, stop held-time) ─
    _print_risk_math(all_trades, out)

    # ── 3. Feature-gap table, automatically for every strategy with enough trades ─
    _print_feature_gaps(all_trades, out)

    # ── 4. Optional raw ADX-signal funnel (own fetch — different kind of scan) ─
    if adx_funnel_strategy:
        _print_adx_funnel(alpaca, tickers, adx_funnel_strategy, out)

    print(f"\nTotal elapsed: {_fmt_elapsed(t_start)}", file=out)


def _print_expectancy_table(all_trades: list[dict], out) -> None:
    agg: dict = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0})
    for t in all_trades:
        sid = t.get("strategy_id", "UNKNOWN")
        agg[sid]["trades"] += 1
        agg[sid]["pnl"]    += t.get("pnl", 0.0)
        if t.get("pnl", 0.0) > 0:
            agg[sid]["wins"] += 1

    print("\n" + "=" * 100, file=out)
    print("1. PER-STRATEGY EXPECTANCY", file=out)
    print("=" * 100, file=out)
    print(f"{'STRATEGY':<12} {'TRADES':>7} {'WIN%':>6} {'TOTAL P&L':>11} {'EXPECTANCY':>11}  VERDICT", file=out)
    print("-" * 100, file=out)

    def _exp(s):
        return s["pnl"] / s["trades"] if s["trades"] else 0.0

    for sid, s in sorted(agg.items(), key=lambda kv: -_exp(kv[1])):
        n, wr, exp = s["trades"], (s["wins"] / s["trades"] * 100 if s["trades"] else 0), _exp(s)
        if n < 10:
            verdict = "⚪ too few trades to judge"
        elif exp > 5:
            verdict = "🟢 keep enabled"
        elif exp > 0:
            verdict = "🟡 marginal — watch"
        else:
            verdict = "🔴 negative expectancy"
        print(f"{sid:<12} {n:>7} {wr:>5.0f}% {s['pnl']:>+10.2f}$ {exp:>+10.2f}$  {verdict}", file=out)


def _print_risk_math(all_trades: list[dict], out) -> None:
    per_strat: dict = defaultdict(lambda: {
        "wins": [], "losses": [], "reasons": defaultdict(int),
        "win_reasons": defaultdict(int), "loss_reasons": defaultdict(int),
    })
    for t in all_trades:
        sid = t.get("strategy_id", "UNKNOWN")
        pnl = t.get("pnl", 0.0)
        d = per_strat[sid]
        (d["wins"] if pnl > 0 else d["losses"]).append(pnl)
        reason = str(t.get("exit_reason", "unknown")).split(" (")[0]
        d["reasons"][reason] += 1
        # 2026-07-21: split win-side vs loss-side exit reasons. The aggregate
        # mix above can't answer "are winners getting cut before they reach a
        # real profit-lock" — this can. If stage1_50pct is rare/absent on the
        # WIN side specifically (not just overall) while peak_giveback/
        # time_cap_loser/momentum_dead dominate wins too, that's evidence the
        # +50% stage1 profit bar is too high for how far these trades
        # actually run before reversing — an exit-engine issue, not entries.
        (d["win_reasons"] if pnl > 0 else d["loss_reasons"])[reason] += 1

    print("\n" + "=" * 100, file=out)
    print("2. RISK MATH — realized win:loss vs. configured gate, exit-reason mix", file=out)
    print("=" * 100, file=out)
    for sid, d in sorted(per_strat.items(), key=lambda kv: -(len(kv[1]["wins"]) + len(kv[1]["losses"]))):
        n = len(d["wins"]) + len(d["losses"])
        avg_w = sum(d["wins"]) / len(d["wins"]) if d["wins"] else 0.0
        avg_l = abs(sum(d["losses"]) / len(d["losses"])) if d["losses"] else 0.0
        rr = (avg_w / avg_l) if avg_l else None
        print(f"\n{sid} ({_STRAT_NAMES.get(sid, sid)}) — n={n}", file=out)
        print(f"  avg win ${avg_w:.2f}  avg loss ${avg_l:.2f}  "
              f"realized W:L {f'{rr:.2f}x' if rr else '—'}  (gate requires 1.2x-1.6x)", file=out)
        top = sorted(d["reasons"].items(), key=lambda kv: -kv[1])[:4]
        print("  exit mix: " + ", ".join(f"{r} ({n})" for r, n in top), file=out)

        win_top  = sorted(d["win_reasons"].items(),  key=lambda kv: -kv[1])[:4]
        loss_top = sorted(d["loss_reasons"].items(), key=lambda kv: -kv[1])[:4]
        if win_top:
            print("  WIN exits:  " + ", ".join(f"{r} ({n})" for r, n in win_top), file=out)
        if loss_top:
            print("  LOSS exits: " + ", ".join(f"{r} ({n})" for r, n in loss_top), file=out)
        _win_n = len(d["wins"])
        # 2026-07-21: prefix match, not exact "stage1_50pct" — stage1 now has
        # 4 possible sub-reasons (ATR target / momentum fade / volume fade /
        # static fallback) since the dynamic trigger fix. Exact-match here
        # would wrongly report 0 stage1 wins even when the dynamic trigger
        # IS firing, just under a different reason string.
        _stage1_wins = sum(v for k, v in d["win_reasons"].items() if k.startswith("stage1"))
        if _win_n >= 3 and _stage1_wins == 0:
            print(
                f"  ⚠️  {_win_n} winning trades, ZERO via any stage1 trigger — winners "
                f"are exiting before the profit-lock ever fires (giveback/time-cap/"
                f"momentum-dead instead). Suggests the exit engine may be capping "
                f"upside, not that entries are bad.",
                file=out,
            )

        # SANITY CHECK (added 2026-07-21, after a real bug slipped through):
        # a broken exit-sim gate once made "atr_trail_stop" cover 87-100% of
        # every strategy's exits, and it read as "strategies are just bad"
        # instead of "the exit engine is broken" until someone eyeballed the
        # exit mix by hand. Flag lopsided exit-reason concentration up front
        # so a single dominant reason gets questioned BEFORE trusting the P&L.
        if n >= 5 and top:
            _top_reason, _top_count = top[0]
            _top_share = _top_count / n
            if _top_share >= 0.70:
                print(
                    f"  ⚠️  SANITY CHECK: '{_top_reason}' is {_top_share*100:.0f}% of exits "
                    f"({_top_count}/{n}). A single exit reason dominating this heavily usually "
                    f"means a gate/condition in the exit engine, not the strategy's entries, "
                    f"is driving the result — verify the exit logic before trusting this P&L.",
                    file=out,
                )


def _print_feature_gaps(all_trades: list[dict], out) -> None:
    by_strat: dict = defaultdict(list)
    for t in all_trades:
        by_strat[t.get("strategy_id", "UNKNOWN")].append(t)

    print("\n" + "=" * 100, file=out)
    print("3. WIN vs LOSS FEATURE GAPS (per strategy, only where n >= "
          f"{MIN_TRADES_FOR_FEATURES})", file=out)
    print("=" * 100, file=out)

    for sid, trades in sorted(by_strat.items(), key=lambda kv: -len(kv[1])):
        if len(trades) < MIN_TRADES_FOR_FEATURES:
            print(f"\n{sid}: n={len(trades)} — below the {MIN_TRADES_FOR_FEATURES}-trade "
                  f"floor, skipping (would just be noise).", file=out)
            continue

        wins   = [t for t in trades if t["pnl"] > 0]
        losses = [t for t in trades if t["pnl"] <= 0]

        meta_keys: set = set()
        for t in trades:
            for k, v in (t.get("entry_meta") or {}).items():
                if isinstance(v, (int, float)):
                    meta_keys.add(k)

        def _avg(rows, key):
            vals = [r.get(key, 0.0) for r in rows]
            return sum(vals) / len(vals) if vals else 0.0

        def _avg_meta(rows, key):
            vals = [(r.get("entry_meta") or {}).get(key) for r in rows]
            vals = [v for v in vals if isinstance(v, (int, float))]
            return sum(vals) / len(vals) if vals else 0.0

        print(f"\n{sid} ({_STRAT_NAMES.get(sid, sid)}) — n={len(trades)}, "
              f"win rate {len(wins)/len(trades)*100:.0f}%", file=out)
        header = f"  {'':<8} {'N':>4} {'avg RVOL':>9} {'avg conf':>9} {'avg held(m)':>12}"
        for k in sorted(meta_keys):
            header += f" {('avg ' + k):>16}"
        print(header, file=out)
        for label, rows in (("WINS", wins), ("LOSSES", losses)):
            line = f"  {label:<8} {len(rows):>4} {_avg(rows,'entry_rvol'):>9.2f} " \
                   f"{_avg(rows,'entry_confidence'):>9.2f} {_avg(rows,'held_minutes'):>12.1f}"
            for k in sorted(meta_keys):
                line += f" {_avg_meta(rows, k):>16.2f}"
            print(line, file=out)


def _print_adx_funnel(alpaca, tickers: list[str], strategy_id: str, out) -> None:
    """Raw ADX-signal funnel for one strategy — needs its own fetch since it
    inspects signals BEFORE the router/backtester ever sees them. Same logic
    as diag_mid_brk_adx_funnel.py, generalized to any ADX-gated strategy."""
    import importlib
    import pandas as pd
    from signals import bars_to_df, compute_rvol, compute_vwap_bands
    from regime_manager import compute_adx_series, ADX_MIN, ADX_GATED_STRATEGIES

    print("\n" + "=" * 100, file=out)
    print(f"4. RAW ADX-SIGNAL FUNNEL — {strategy_id}", file=out)
    print("=" * 100, file=out)

    if strategy_id not in ADX_GATED_STRATEGIES:
        print(f"{strategy_id} is not in ADX_GATED_STRATEGIES — this gate doesn't apply to it.",
              file=out)
        return

    try:
        strat_module = importlib.import_module(f"strategies.{strategy_id.lower()}")
    except ImportError:
        print(f"Could not import strategies.{strategy_id.lower()} — check the strategy ID.", file=out)
        return

    all_signals: list[dict] = []
    for ticker in tickers:
        print(f"  ⏳ funnel scan: {ticker}…", file=out, flush=True)
        try:
            import yfinance as yf
            import datetime as _dt
            _today = _dt.date.today()
            raw = yf.download(ticker, start=(_today - _dt.timedelta(days=59)).strftime("%Y-%m-%d"),
                               end=(_today + _dt.timedelta(days=1)).strftime("%Y-%m-%d"),
                               interval="5m", progress=False, auto_adjust=True)
            if raw.empty:
                continue
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
            raw2 = alpaca.get_bars(ticker, "5Min", limit=10000)
            bars = raw2[0] if isinstance(raw2, tuple) else raw2
            if not bars:
                continue
            df = bars_to_df(bars)

        if df.empty or len(df) < 100:
            continue

        df["rvol"]  = compute_rvol(df, lookback_days=10)
        df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()
        vwap_frame  = compute_vwap_bands(df, num_stds=(1, 2))
        df["vwap"]  = vwap_frame["vwap"].ffill()

        adx_series = compute_adx_series(df)
        df["_date"] = df["time"].dt.date
        for day, day_df in df.groupby("_date"):
            day_df = day_df.reset_index(drop=True)
            if len(day_df) < 15:
                continue
            for i in range(10, len(day_df)):
                slice_df = day_df.iloc[: i + 1].reset_index(drop=True)
                try:
                    sig = strat_module.evaluate(slice_df, ticker=ticker)
                except Exception:
                    continue
                if sig is None:
                    continue
                bar_time = day_df.iloc[i]["time"]
                adx_val = None
                if adx_series is not None and not adx_series.empty:
                    prior = adx_series[adx_series.index <= bar_time]
                    if not prior.empty:
                        adx_val = float(prior.iloc[-1])
                passes_adx = (adx_val is None) or (adx_val >= ADX_MIN)
                fwd_idx = i + 12
                fwd_pct = None
                if fwd_idx < len(day_df):
                    entry_px = float(day_df.iloc[i]["close"])
                    fwd_px   = float(day_df.iloc[fwd_idx]["close"])
                    fwd_pct  = (fwd_px - entry_px) / entry_px * 100
                all_signals.append({
                    "adx": adx_val, "passes_adx_gate": passes_adx,
                    "fwd_pct": fwd_pct, "worked": fwd_pct is not None and fwd_pct < -0.10,
                })

    total = len(all_signals)
    print(f"\nTotal raw signals: {total}", file=out)
    if total == 0:
        print("No raw signals found — nothing to funnel.", file=out)
        return

    passed  = [s for s in all_signals if s["passes_adx_gate"]]
    blocked = [s for s in all_signals if not s["passes_adx_gate"]]
    print(f"Survive ADX >= {ADX_MIN:.0f}: {len(passed)}/{total} ({len(passed)/total*100:.0f}%)  "
          f"Blocked: {len(blocked)}/{total} ({len(blocked)/total*100:.0f}%)", file=out)

    for label, rows in (("BLOCKED", blocked), ("SURVIVING", passed)):
        rows_fwd = [r for r in rows if r["fwd_pct"] is not None]
        if not rows_fwd:
            continue
        wins = sum(1 for r in rows_fwd if r["worked"])
        avg  = sum(r["fwd_pct"] for r in rows_fwd) / len(rows_fwd)
        print(f"  {label}: n={len(rows_fwd)}  worked={wins} ({wins/len(rows_fwd)*100:.0f}%)  "
              f"avg 60m fwd={avg:+.3f}%", file=out)


if __name__ == "__main__":
    main()

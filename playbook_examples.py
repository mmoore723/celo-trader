"""
playbook_examples.py — Mines REAL historical examples of each of the 8 strategies
firing, for use on the Playbooks education page.

Why this exists (2026-06-20 audit)
───────────────────────────────────
The Playbooks page previously illustrated every strategy with _gen_orb_scenario()
in dashboard.py — randomly generated, fabricated candles. That's a real
credibility problem for something people pay to learn from: a synthetic, made-up
chart undermines trust in a strategy you're asking someone to pay for.

This module walks REAL historical 5-min bars through the SAME indicator-building
and strategy-evaluation functions the live bot uses every tick (_build_indicator_frame
+ the eight _eval_* functions in strategy_router.py), finds genuine fire events, and
classifies what actually happened afterward (favorable move / reversal / chop) —
so Playbooks can show a real ticker, on a real date, doing a real thing.

We deliberately do NOT call route_signals() directly — it gates on check_kill_lock(),
which reflects the LIVE bot's current trading-halt state. That guard is meaningless
for offline historical analysis and would silently return zero signals if the live
bot happened to be kill-locked at the moment someone re-runs this script. Calling
the eval functions directly bypasses that, which is correct here.

Usage
─────
  Run standalone to (re)generate the cache file:
      python playbook_examples.py
  Or call mine_all_examples() from the dashboard (wired to a "🔄 Regenerate
  examples" button) so re-running doesn't require a terminal.

  Requires network access to Alpaca (same credentials as the live bot, via
  .env). This will NOT work in an offline/sandboxed environment — it needs to
  run wherever the bot itself normally runs.

Output
──────
  playbook_examples.json — keyed by strategy_id, each holding a list of
  {ticker, date, direction, confidence, rvol, outcome, signal_idx, entry_idx,
   exit_idx, bars: [real OHLCV window]} records ready for charting.

Known gap (as of 2026-06-20)
─────────────────────────────
MID_BRK and AFT_REV have never fired in any real session logged so far
(confirmed via trades_paper.db system_events — zero narration for either).
Until they fire for real, mine_all_examples() returns fewer than
max_examples_per_strategy for those two, or none at all on a fresh run. The
Playbooks page MUST render an honest "no real example yet — strategy hasn't
fired in live trading" state for any strategy missing from the output rather
than fabricating one. Do not special-case these back into synthetic data.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from config import TICKER_UNIVERSE
from signals import bars_to_df, compute_vwap

logger = logging.getLogger("celo_trader.playbook_examples")

EXAMPLES_PATH = Path(__file__).resolve().parent / "playbook_examples.json"

# How many bars forward to look when classifying a signal's real outcome.
_OUTCOME_LOOKAHEAD = 12   # ~60 min of 5-min bars — matches the bot's 45-min time-box + margin

# Underlying-price move proxy for "this signal was followed by a real,
# directionally-correct, meaningful move" — used only to pick which real
# historical instance to show as "clean_win" vs "reversed" vs "chopped", never
# to compute or display any P&L as fact.
#
# CALIBRATION HISTORY (2026-06-20, same day as first written — twice corrected):
#   v1: 0.012 (1.2%) — reasoned from "a Stage-1 +50% option hit needs ~1.2%
#       underlying move." Wrong: real winning trades exit at modest 10-20%
#       premium gains via early timebox, not +50% Stage-1. Result: 24/24 real
#       mined signals classified "chopped" — including a real SPY move of
#       -0.37% that's clearly a genuine, directional move, just below the bar.
#   v2: 0.004 (0.4%) — lowered, but checked against the actual distribution of
#       best-favorable-move-seen across all 24 real examples and found only
#       1/24 cleared it. Still too strict for what SPY (the ticker most of
#       these examples happen to be) actually does in a 60-min window.
#   v3 (current): 0.0018 (0.18%) — set at roughly the 70th percentile of the
#       REAL observed move distribution from this mining run (sorted moves
#       ran from -0.05% to +0.43%, median ~0.08%). This puts a reasonable
#       minority of examples in "clean_win" — the genuinely better moves —
#       while most stay "chopped"/"reversed", which matches reality: most
#       signals don't produce huge moves, and an honest example set should
#       reflect that mix rather than be tuned to make everything look good.
# Revisit this if mining ever covers more volatile tickers (TSLA/NVDA) in
# bulk, since a single flat threshold across very different tickers' typical
# volatility is a known simplification, not a universal constant.
_FAVORABLE_MOVE_PROXY = 0.0018

# Evaluator table — imported directly rather than via route_signals() so this
# offline mining run is NOT gated by check_kill_lock() (see module docstring).
from strategy_router import (
    _build_indicator_frame,
    _eval_inst_orb,
    _eval_bos_mss,
    _eval_vwap_pullback,
    _eval_fvg,
    _eval_midday_breakdown,
    _eval_afternoon_reversal,
    _eval_trend_cont,
    _eval_chan_break,
    _get_dynamic_rvol_threshold,
    MarketStructureAnalyzer,
)

# Fixed (non-dynamic) RVOL gates for the 4 strategies that don't call
# _get_dynamic_rvol_threshold() at all — read directly off the literal
# comparisons in strategy_router.py (`rvol >= 1.5`, `c_rvol < 1.5`, etc.),
# not off docstrings, which have drifted from the real code more than once
# this session. AFT_REV has NO RVOL floor (gates on raw volume vs its 20-bar
# SMA instead) so it's intentionally absent here — None means "not gated".
_FIXED_RVOL_GATES = {
    "BOS_MSS":    1.5,
    "FVG":        1.5,
    "TREND_CONT": 1.2,
}


def _real_rvol_gate(strategy_id: str, today: pd.DataFrame, sig) -> float | None:
    """
    Return the RVOL threshold that ACTUALLY applied to a real mined signal —
    read by re-deriving it the same way strategy_router.py's own eval
    functions do, not a static per-strategy assumption.

    Why this exists (2026-06-20): the Playbooks page was showing a fixed
    "needs >= X%" number per strategy that came from stale docstrings/notes,
    not the real code. strategy_router.py's _get_dynamic_rvol_threshold()
    means 4 of the 8 strategies (INST_ORB, VWAP_PB, MID_BRK, CHAN_BREAK) use
    a CONTEXT-DEPENDENT gate that drops from 1.2x to 1.0x once market
    structure is already confirmed — a real example showing "RVOL 1.01x"
    passing a supposedly ">=1.3x" gate was this exact bug, not a fluke.
    This function is read-only and duplicates strategy_router's msa_confirmed
    derivation ONLY for display purposes — it never feeds back into any
    trading decision, so it carries none of the risk a change to the live
    eval functions would.
    """
    last_bar = today.iloc[-1]
    bar_min  = last_bar["time"].hour * 60 + last_bar["time"].minute
    close    = float(last_bar["close"])
    vwap     = float(last_bar["vwap"]) if not pd.isna(last_bar.get("vwap", np.nan)) else None
    msa      = MarketStructureAnalyzer(today)

    if strategy_id == "INST_ORB":
        msa_ok = (msa.confirmed_lower_high() if sig.direction == "bearish"
                  else msa.confirmed_higher_low())
        or_low = sig.meta.get("or_low") if sig.meta else None
        return _get_dynamic_rvol_threshold(bar_min, close, or_low, vwap, "INST_ORB", msa_confirmed=msa_ok)
    if strategy_id == "VWAP_PB":
        msa_ok = (msa.confirmed_lower_high() if sig.direction == "bearish"
                  else msa.confirmed_higher_low())
        return _get_dynamic_rvol_threshold(bar_min, close, None, vwap, "VWAP_PB", msa_confirmed=msa_ok)
    if strategy_id == "MID_BRK":
        or_low = sig.meta.get("or_low") if sig.meta else None
        return _get_dynamic_rvol_threshold(bar_min, close, or_low, vwap, "MID_BRK", msa_confirmed=True)
    if strategy_id == "CHAN_BREAK":
        return _get_dynamic_rvol_threshold(bar_min, close, None, vwap, "CHAN_BREAK", msa_confirmed=True)
    return _FIXED_RVOL_GATES.get(strategy_id)   # fixed gate, or None (AFT_REV — no RVOL floor)

# How many bars of margin to pad around the display window when running swing
# (SH/SL) pivot detection — MarketStructureAnalyzer needs LOOKBACK (5) bars on
# BOTH sides of a candidate bar to confirm it as a pivot, so without this
# padding we'd silently miss pivots near the edges of the visible window.
_SWING_CONTEXT_PAD = MarketStructureAnalyzer.LOOKBACK + 1

_EVALUATORS = [
    ("INST_ORB",   _eval_inst_orb),
    ("BOS_MSS",    _eval_bos_mss),
    ("VWAP_PB",    _eval_vwap_pullback),
    ("FVG",        _eval_fvg),
    ("MID_BRK",    _eval_midday_breakdown),
    ("AFT_REV",    _eval_afternoon_reversal),
    ("TREND_CONT", _eval_trend_cont),
    ("CHAN_BREAK", _eval_chan_break),
]


def _classify_outcome(df: pd.DataFrame, signal_idx: int, direction: str) -> tuple[str, int]:
    """
    Look forward from the real signal bar and classify what actually happened.

    Returns (outcome, exit_idx):
      "clean_win" — price moved favorably enough to proxy a Stage-1 (+50% option) hit
      "reversed"  — price moved against the signal sharply (would have hard-stopped)
      "chopped"   — price went nowhere meaningful within the lookahead window

    FIX 2026-06-20: the lookahead used to run purely on bar COUNT
    (signal_idx + 1 .. +12), with no awareness that `df` is a continuous
    multi-day series. A signal fired late in a session (e.g. 3:40pm) would
    pull its "next 12 bars" from the FOLLOWING trading day — a real overnight
    gap of many hours. That gap doesn't just look odd in the underlying data;
    it broke the Playbooks chart rendering entirely, because Lightweight
    Charts plots bars on a real continuous time axis: an 18-hour overnight
    gap inside a 20-bar window made the actual candles render as a tiny
    sliver crushed against one edge, with most of the chart empty. Capping
    the lookahead (and, in mine_strategy_examples below, the chart window)
    to the SAME calendar day as the signal fixes both the data and the
    rendering — and is also just more honest: a real trader watching this
    strategy intraday isn't holding through the close into tomorrow morning.
    """
    _signal_date = df.iloc[signal_idx]["time"].date()
    end = min(signal_idx + 1 + _OUTCOME_LOOKAHEAD, len(df))
    fwd = df.iloc[signal_idx + 1:end]
    fwd = fwd[fwd["time"].apply(lambda t: t.date()) == _signal_date]
    if fwd.empty:
        return "chopped", signal_idx

    entry_price = df.iloc[signal_idx]["close"]
    sign = 1 if direction == "bullish" else -1

    # Signed so positive = favorable regardless of CALL/PUT direction.
    fwd_moves = (fwd["close"] - entry_price) / entry_price * sign

    best_rel  = int(fwd_moves.values.argmax())
    worst_rel = int(fwd_moves.values.argmin())
    best_move  = fwd_moves.iloc[best_rel]
    worst_move = fwd_moves.iloc[worst_rel]

    if best_move >= _FAVORABLE_MOVE_PROXY:
        return "clean_win", signal_idx + 1 + best_rel
    if worst_move <= -_FAVORABLE_MOVE_PROXY:
        return "reversed", signal_idx + 1 + worst_rel
    return "chopped", signal_idx + 1 + len(fwd) - 1


def mine_strategy_examples(
    alpaca,
    tickers: list[str] | None = None,
    bars_per_ticker: int = 1500,
    max_examples_per_strategy: int = 3,
) -> dict:
    """
    Walk real historical 5-min bars for each ticker through the actual
    indicator-building + strategy-evaluation pipeline, bar by bar, exactly as
    the live bot's tick loop does (evaluating only data that was actually
    available "as of" that bar — no lookahead in the SIGNAL detection itself;
    lookahead is only used afterward, in _classify_outcome, to label what
    really happened next). No synthetic/fabricated prices anywhere here.

    bars_per_ticker=1500 mirrors the ~15-day 5Min history window already used
    elsewhere in this codebase for RVOL baseline (trading_logic.py's historical
    augment) — same Alpaca free-tier IEX constraint applies.

    This is an offline batch job: ~5 tickers × ~1500 bars × 8 strategies. Expect
    it to take a few minutes — it's meant to be re-run occasionally (e.g. after
    a quiet week adds more candidate signals), not on every page load.
    """
    tickers = tickers or TICKER_UNIVERSE
    examples: dict[str, list[dict]] = {}
    seen: set[tuple] = set()   # (ticker, date, strategy_id) — one fire per ticker/day/strategy

    for ticker in tickers:
        try:
            bars, is_error = alpaca.get_bars(ticker, "5Min", limit=bars_per_ticker)
        except Exception as e:
            logger.error("mine_strategy_examples: get_bars failed for %s: %s", ticker, e)
            continue
        if is_error or not bars:
            logger.warning("mine_strategy_examples: no bars for %s — skipping", ticker)
            continue

        df = bars_to_df(bars)
        if df.empty or len(df) < 30:
            continue

        # Anchored VWAP over the WHOLE multi-day series (resets each calendar
        # day internally) — computed once per ticker so every example's chart
        # can show the real VWAP line the strategy's own VWAP gate references,
        # instead of leaving "VWAP Gate" as text the reader has to take on faith.
        _vwap_series = compute_vwap(df)

        # Skip the first ~25 bars so indicator warmup (RVOL baseline, VWAP
        # accumulation) has real prior data to work from before we trust a signal.
        for i in range(25, len(df)):
            if all(len(v) >= max_examples_per_strategy for v in examples.values()) and \
               len(examples) == len(_EVALUATORS):
                break   # every strategy already has enough examples — stop early

            truncated = df.iloc[: i + 1]
            try:
                today = _build_indicator_frame(truncated)
            except Exception as e:
                logger.debug("indicator build failed at bar %d for %s: %s", i, ticker, e)
                continue
            if today.empty:
                continue

            day_key = truncated["time"].iloc[-1].date()

            for strategy_id, fn in _EVALUATORS:
                if len(examples.get(strategy_id, [])) >= max_examples_per_strategy:
                    continue
                key = (ticker, day_key, strategy_id)
                if key in seen:
                    continue
                try:
                    sig = fn(today)
                except Exception as e:
                    logger.debug("%s eval failed at bar %d for %s: %s", strategy_id, i, ticker, e)
                    continue
                if sig is None:
                    continue
                seen.add(key)

                # Real applicable RVOL gate for THIS signal — re-derived from
                # strategy_router's own dynamic-threshold logic, not a static
                # assumption. See _real_rvol_gate() docstring for why this
                # matters (a real example clearing "1.01x" against a
                # displayed ">=1.3x" gate was exactly this bug).
                try:
                    _rvol_gate = _real_rvol_gate(strategy_id, today, sig)
                except Exception as e:
                    logger.debug("rvol gate re-derivation failed for %s: %s", strategy_id, e)
                    _rvol_gate = None

                outcome, exit_idx = _classify_outcome(df, i, sig.direction)

                # Real OHLCV window for charting: pre-signal context through
                # the classified exit (or lookahead window end).
                # FIX 2026-06-20 (widened 6 -> 40 bars): direct user feedback
                # — "just 13 candles is not enough to get the full picture."
                # 6 bars of context (~30 min) cropped out exactly the
                # structure (trend, swing highs/lows) that justified a call,
                # so the chart looked disconnected from its own label even
                # when the underlying signal logic was legitimate (see the
                # BOS_MSS SPY 2026-05-26 case earlier this session — the real
                # swing pair was outside the old 6-bar window). 40 bars
                # (~3.3 hours of 5-min bars) gives enough runway to actually
                # see the structure the bot is reacting to, while still
                # clamping to the signal's own calendar day below.
                _signal_day = df.iloc[i]["time"].date()
                window_start = max(0, i - 40)
                while window_start < i and df.iloc[window_start]["time"].date() != _signal_day:
                    window_start += 1
                window_end = min(len(df), exit_idx + 2)
                window = df.iloc[window_start:window_end].reset_index(drop=True)

                # ── Structural overlays — real, not illustrative ────────────
                # VWAP: slice the same window range out of the per-ticker
                # anchored series computed above, so it's aligned bar-for-bar.
                _vwap_window = [
                    (round(float(v), 4) if pd.notna(v) else None)
                    for v in _vwap_series.iloc[window_start:window_end]
                ]

                # Opening Range high/low: constant for the whole session, so
                # a flat reference level across the window is accurate — only
                # populated for strategies whose eval function actually used
                # it (INST_ORB, MID_BRK); everyone else gets None and the
                # chart simply omits the line.
                _or_high = sig.meta.get("or_high") if sig.meta else None
                _or_low  = sig.meta.get("or_low")  if sig.meta else None

                # Swing high/low pivots: re-run the SAME 5-bar-lookback pivot
                # detector the bot's MarketStructureAnalyzer uses, but on a
                # padded slice of `df` so pivots that fall anywhere inside the
                # display window — including AFTER the signal bar — get
                # caught (the live bot only ever looks backward as of each
                # tick; here we want everything visible in the static window).
                # FIX 2026-06-20: a real example (BOS_MSS, SPY 2026-05-26)
                # showed a "SL" swing-low marker sitting right after the
                # entry, which a viewer reasonably read as "the structure
                # that caused this bearish call" — except that low formed
                # AFTER the signal even fired, so it's physically impossible
                # it caused anything. Tagging before_signal lets the chart
                # tell those two cases apart instead of presenting both
                # identically.
                _ctx_start = max(0, window_start - _SWING_CONTEXT_PAD)
                _ctx_end   = min(len(df), window_end + _SWING_CONTEXT_PAD)
                _ctx_df    = df.iloc[_ctx_start:_ctx_end].reset_index(drop=True)
                _swing_points = []
                try:
                    for s in MarketStructureAnalyzer(_ctx_df).swings:
                        _global_idx = _ctx_start + s["idx"]
                        if window_start <= _global_idx < window_end:
                            _swing_points.append({
                                "idx":           _global_idx - window_start,
                                "price":         round(s["price"], 4),
                                "type":          s["type"],   # "high" | "low"
                                "before_signal": _global_idx <= i,
                            })
                except Exception as e:
                    logger.debug("swing detection failed for %s example: %s", strategy_id, e)

                # Persist whatever the live eval function recorded as its own
                # decision basis (e.g. BOS_MSS's prior_swing_high/prior_swing_low/
                # last_high/prev_high) so the Signal card can quote the EXACT
                # price levels the bot used — even when those pivots sit
                # outside this example's ~20-bar display window and so can't
                # be drawn on the chart itself. Round floats; drop anything
                # that isn't JSON-plain (e.g. a stray Timestamp).
                _signal_meta = {}
                if sig.meta:
                    for _k, _v in sig.meta.items():
                        if isinstance(_v, (int, float)) and not isinstance(_v, bool):
                            _signal_meta[_k] = round(float(_v), 4)
                        elif isinstance(_v, (str, bool)) or _v is None:
                            _signal_meta[_k] = _v

                examples.setdefault(strategy_id, []).append({
                    "ticker":       ticker,
                    "date":         str(day_key),
                    "direction":    sig.direction,
                    "confidence":   round(float(sig.confidence), 3),
                    "rvol":         round(float(sig.rvol), 2),
                    "outcome":      outcome,
                    "signal_idx":   i - window_start,
                    "entry_idx":    min(i - window_start + 1, len(window) - 1),
                    "exit_idx":     min(exit_idx - window_start, len(window) - 1),
                    "vwap":         _vwap_window,
                    "or_high":      round(float(_or_high), 4) if _or_high is not None else None,
                    "or_low":       round(float(_or_low), 4) if _or_low is not None else None,
                    "swing_points": _swing_points,
                    "rvol_gate":    round(float(_rvol_gate), 2) if _rvol_gate is not None else None,
                    "signal_meta":  _signal_meta,
                    "bars": [
                        {
                            "time":   str(row["time"]),
                            "open":   round(float(row["open"]), 4),
                            "high":   round(float(row["high"]), 4),
                            "low":    round(float(row["low"]), 4),
                            "close":  round(float(row["close"]), 4),
                            "volume": int(row["volume"]),
                        }
                        for _, row in window.iterrows()
                    ],
                })

    return examples


def mine_all_examples(save: bool = True) -> dict:
    """Entry point — fetches real bars via Alpaca and mines all 8 strategies."""
    from broker import get_clients
    alpaca, _tradier = get_clients()
    examples = mine_strategy_examples(alpaca)

    # Strategies with zero real fires are intentionally left OUT of the dict
    # (not filled with a placeholder) — see module docstring re: MID_BRK / AFT_REV.
    for strategy_id, _fn in _EVALUATORS:
        if strategy_id not in examples:
            logger.warning(
                "No real examples found for %s — it hasn't fired in this "
                "historical window. Playbooks must show 'awaiting real signal', "
                "not a fabricated example.", strategy_id,
            )

    if save:
        save_examples(examples)
    return examples


def save_examples(examples: dict, path: Path = EXAMPLES_PATH) -> None:
    with open(path, "w") as f:
        json.dump({
            "generated_at": datetime.utcnow().isoformat(),
            "examples":     examples,
        }, f, indent=2)
    logger.info("Saved real playbook examples to %s (%d strategies represented)",
                path, len(examples))


def load_examples(path: Path = EXAMPLES_PATH) -> dict:
    """
    Load the cached real examples. Returns {} if the cache doesn't exist yet
    (e.g. fresh install before the first mining run, or this exact file has
    never been regenerated) — callers MUST handle the empty/missing-strategy
    case by showing an honest "no real example yet" state, never by silently
    falling back to fabricated data.
    """
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            data = json.load(f)
        return data.get("examples", {})
    except Exception as e:
        logger.error("load_examples failed: %s", e)
        return {}


if __name__ == "__main__":
    import logging as _lg
    _lg.basicConfig(level=_lg.INFO)
    result = mine_all_examples()
    print("\n=== Real example mining complete ===")
    for strategy_id, _fn in _EVALUATORS:
        n = len(result.get(strategy_id, []))
        status = f"{n} real example(s)" if n else "NONE — hasn't fired in this window yet"
        print(f"  {strategy_id:12} {status}")

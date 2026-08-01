"""
playbook_examples/mining.py — mine_strategy_examples(): walks real
historical bars through the live evaluator pipeline bar-by-bar and records
genuine fire events for the Playbooks page.

Split out of the old single playbook_examples.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.

Kept as one function — it's a single bar-by-bar mining loop threading a lot
of local mutable state (examples dict, seen set, per-signal window/overlay
computation) through one cohesive pass; splitting it further would mean
passing that same state through several function-call boundaries for no
real readability gain, matching the "irreducible function" exception
already applied elsewhere this session (e.g. trading/entry/tick.py's
_tick, backtester/simulate.py's _simulate_day).
"""

import logging

import pandas as pd

from config import TICKER_UNIVERSE
from signals import bars_to_df, compute_vwap
from playbook_examples.evaluators import _EVALUATORS, _SWING_CONTEXT_PAD
from playbook_examples.evaluators import MarketStructureAnalyzer
from playbook_examples.outcome import _classify_outcome
from playbook_examples.rvol_gates import _real_rvol_gate

logger = logging.getLogger("celo_trader.playbook_examples")


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
    from strategy_router import _build_indicator_frame

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

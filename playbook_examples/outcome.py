"""
playbook_examples/outcome.py — _classify_outcome(): labels what a real
historical signal was actually followed by (clean_win / reversed / chopped).

Split out of the old single playbook_examples.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""

import pandas as pd

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

"""
strategies/trend_cont/__init__.py — Trend Continuation (TREND_CONT)

Session: 09:45–14:30 ET | Direction: both

Enters on LH re-entry (bearish) or HL re-entry (bullish) — the second/third
entry AFTER trend has already been proven.  The pivot must be within 10 bars
(fresh, not stale).

Gates:
  1. Session: 09:45–14:30 ET
  2. RVOL ≥ 1.2× (trend already proven; lower threshold than ORB)
  3. MSA confirmed downtrend + LH  OR  uptrend + HL
  4. Pivot ≤ 10 bars old
  5. Current bar closes below LH close (bearish) or above HL close (bullish)
  6. VWAP alignment (soft — blocks but logs)

2026-07-17: _MAX_BARS tightened 20 -> 10. diag_trend_cont_features.py found
a real gap between winning and losing trades: winners re-entered on a fresh
pivot (avg 4 bars ago), losers on a stale one (avg 9 bars ago). A/B tested
via ab_test_trend_cont_maxbars.py: 20 bars = 58.3% WR, +$41.25/trade;
10 bars = 70.0% WR, +$73.01/trade. Shipped after the improvement confirmed.

2026-07-21: run_full_audit.py (post window-fix, backtester-fidelity-fix) still
showed TREND_CONT at -$35.71/trade expectancy, 35% WR (n=26). The win/loss
gap is now WITHIN the existing 10-bar cap: winners re-enter on an even
fresher pivot (avg 4.4 bars ago) than losers (avg 6.0), and winners' pullback
is roughly 2x deeper (lh_depth_pct/hl_rise_pct avg ~1.1%) than losers'
(~0.6%). _MAX_BARS tightened 10 -> 6 and a minimum depth/rise floor added
below, both as HYPOTHESES pending ab_test_v2_fixes.py confirmation —
do not treat these as validated until that backtest comes back positive,
per the same standard the 07-17 change was held to.

Split (2026-08-01, file-size cleanup) out of the old single
strategies/trend_cont.py into constants.py and evaluate.py; no logic
changed, only relocated. _MAX_BARS, _MIN_DEPTH_PCT, and STRUCT_STOP_MODE
are defined/re-exported HERE (not just in constants.py's own namespace, in
the sense that THIS package object is what external monkey-patchers touch)
because archived diagnostic scripts monkey-patch them directly on the
package object at runtime — see constants.py's docstring for the full
mechanics and the list of scripts involved.
"""

from strategies.trend_cont.constants import (
    STRATEGY_ID,
    _RVOL_MIN,
    _MAX_BARS,
    _MIN_DEPTH_PCT,
    STRUCT_STOP_MODE,
)
from strategies.trend_cont.evaluate import evaluate

__all__ = [
    "STRATEGY_ID",
    "_RVOL_MIN",
    "_MAX_BARS",
    "_MIN_DEPTH_PCT",
    "STRUCT_STOP_MODE",
    "evaluate",
]

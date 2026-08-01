"""
strategies/aft_rev/__init__.py — Afternoon Reversal (AFT_REV)

Session: 13:00–15:30 ET | Direction: BOTH (bullish + bearish)

After a sustained morning move, fires when structure shows the first confirmed
reversal pivot followed by a break through the most recent swing level.

  Bullish: confirmed Higher Low + break above most recent Swing High
           (afternoon recovery after mid-day sell-off)
  Bearish: confirmed Lower High + break below most recent Swing Low
           (afternoon distribution after morning rally — mirror pattern)

Gates:
  1. Session: 13:00–15:30 ET
  2. RVOL ≥ 1.0 (afternoon is quieter but still needs real participation)
  3. [Gate 3 REMOVED] — intraday vol_sma inflated by opening spike bar
  4. MSA confirmed Higher Low (bullish) or Lower High (bearish)
  5. Price closes above most recent Swing High (bullish BOS)
       or below most recent Swing Low (bearish BOS)
  Bonus: VWAP alignment adds to confidence (soft gate)

2026-07-21: run_full_audit.py (post window-fix, backtester-fidelity-fix)
showed AFT_REV at -$83.04/trade expectancy, 21% WR (n=19) — the worst win
rate of any active strategy. Two gaps in the win/loss feature comparison:
  1. Winners break out by roughly 2x the margin losers do (breakout_pct
     avg 0.91% vs 0.54% on the bullish path). Added _MIN_BREAKOUT_PCT below
     as a minimum BOS clearance instead of any tick-through counting.
  2. Winners had LOWER average RVOL (1.97) than losers (2.73) — the
     opposite of what the confidence formula assumes. Capped the RVOL bonus
     below instead of removing it outright (n=19 is thin; the bearish-side
     breakdown_pct read the opposite direction on wins/losses and n=4 wins
     is too small to trust a threshold there, so that side is untouched).
Both HYPOTHESES pending ab_test_v2_fixes.py confirmation.

Split (2026-08-01, file-size cleanup) out of the old single
strategies/aft_rev.py into constants.py and evaluate.py; no logic changed,
only relocated. _MIN_BREAKOUT_PCT and _RVOL_BONUS_CAP are defined/
re-exported HERE (not just in constants.py's own namespace, in the sense
that THIS package object is what external monkey-patchers touch) because
an archived diagnostic script monkey-patches them directly on the package
object at runtime — see constants.py's docstring for the full mechanics.
"""

from strategies.aft_rev.constants import (
    STRATEGY_ID,
    _MIN_BREAKOUT_PCT,
    _RVOL_BONUS_CAP,
)
from strategies.aft_rev.evaluate import evaluate

__all__ = [
    "STRATEGY_ID",
    "_MIN_BREAKOUT_PCT",
    "_RVOL_BONUS_CAP",
    "evaluate",
]

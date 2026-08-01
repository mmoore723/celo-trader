"""
strategies/chan_break/__init__.py — Channel Trendline Rejection (CHAN_BREAK)

Session: 09:45–14:00 ET | Direction: both

Short at descending channel upper trendline, long at ascending channel lower
trendline. Requires a touch within 0.3% of the projected level + a close-past-
the-line rejection/bounce candle + RVOL.

Detection (descending channel — bearish):
  1. Find 2 most recent MSA swing highs where SH2 < SH1
  2. Project trendline to current bar
  3. Bar HIGH tags within 0.3% of the projected level
  4. Bar CLOSE is below the projected level (rejection)
  5. VWAP alignment (close < VWAP for bearish)
  6. RVOL ≥ 1.0× (CHAN_BREAK threshold — 0.75× was too permissive)

Mirror logic for ascending channel (bullish).

Split (2026-08-01, file-size cleanup) out of the old single
strategies/chan_break.py into constants.py, descending.py, ascending.py,
and evaluate.py; no logic changed, only relocated. Re-exports STRATEGY_ID
and evaluate so `from strategies import chan_break` + `chan_break.evaluate`
call sites (strategy_router.py) keep working unchanged.
"""

from strategies.chan_break.constants import STRATEGY_ID
from strategies.chan_break.evaluate import evaluate

__all__ = ["STRATEGY_ID", "evaluate"]

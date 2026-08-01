"""
strategies/ifvg/__init__.py — Inverted Fair Value Gap (IFVG)

ICT concept: when a standard 3-candle FVG is fully mitigated (price body-closes
through the far edge of the gap), the zone flips polarity — a bullish imbalance
becomes resistance; a bearish imbalance becomes support.  Entry fires when price
comes back to RETEST the inverted zone.

Signal direction is OPPOSITE to the original gap:
  Bullish FVG fully violated  → IFVG zone = resistance → BEARISH signal (puts)
  Bearish FVG fully violated  → IFVG zone = support    → BULLISH signal (calls)

Hard gates (all must pass):
  1. Liquidity sweep REQUIRED before the original gap formed — unlike FVG where
     it's a confidence bonus, here it is a hard blocker.  Without a sweep the
     zone flip is just price noise, not an institutional reversal.
  2. Full candle BODY close through the far edge (not a wick poke).
  3. Retest of the inverted zone within _RETEST_MAX_BARS bars of the violation.
  4. Original gap formed within the last _GAP_LOOKBACK bars.
  5. RVOL ≥ 1.5 on the retest bar (volume confirms the retest).
  6. VWAP soft gate — conflict reduces confidence -0.05 but does not block.
  7. Each inverted zone fires at most once per session.

Split (2026-08-01, file-size cleanup) out of the old single
strategies/ifvg.py into constants.py, state.py (_consumed_ifvgs), and
evaluate.py; no logic changed, only relocated. No external monkey-patching
found for this module (confirmed via grep before this split), so this
__init__.py's re-exports are plain convenience imports.
"""

from strategies.ifvg.constants import STRATEGY_ID, _GAP_LOOKBACK, _RETEST_MAX_BARS
from strategies.ifvg.state import _consumed_ifvgs
from strategies.ifvg.evaluate import evaluate

__all__ = [
    "STRATEGY_ID",
    "_GAP_LOOKBACK",
    "_RETEST_MAX_BARS",
    "_consumed_ifvgs",
    "evaluate",
]

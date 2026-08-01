"""
strategies/fvg/__init__.py — Fair Value Gap (FVG) with Liquidity Sweep Confirmation

Three-candle imbalance retest. Entry fires when the current bar closes INTO
the gap on the correct side.

BOS_MSS logic is now a built-in quality gate rather than a separate strategy.
A liquidity sweep of a prior swing high/low in the last 15 bars upgrades
confidence (+0.07). Without a sweep the signal still fires but at lower
conviction. This implements the ICT Silver Bullet concept loosely:
  sweep of prior swing → FVG forms in reversal → retest of gap = entry.

Gates:
  1. Gap width ≥ 0.5× ATR14
  2. RVOL ≥ 1.5× on the retest bar
  3. Trend + EMA50 alignment (no counter-trend entries)
  4. VWAP alignment
  5. Gap deduplication (each zone fires once per session)
  6. [Soft] Liquidity sweep check — modifies confidence, does not hard-block

Split (2026-08-01, file-size cleanup) out of the old single
strategies/fvg.py into constants.py, state.py (_consumed_gaps),
sweep.py (_detect_liquidity_sweep), and evaluate.py; no logic changed,
only relocated.

_detect_liquidity_sweep is re-exported here because strategies/ifvg.py
does `from strategies.fvg import _detect_liquidity_sweep` (reusing the ICT
sweep detector) — confirmed via grep before this split, no other external
consumers found. _consumed_gaps has no external consumers; it's mutated IN
PLACE by evaluate.py (never reassigned), so the plain re-export below
keeps the same object identity everywhere, same pattern already used for
strategies/base/cooldown.py's _signal_cooldown.
"""

from strategies.fvg.constants import STRATEGY_ID, _SWEEP_LOOKBACK
from strategies.fvg.state import _consumed_gaps
from strategies.fvg.sweep import _detect_liquidity_sweep
from strategies.fvg.evaluate import evaluate

__all__ = [
    "STRATEGY_ID",
    "_SWEEP_LOOKBACK",
    "_consumed_gaps",
    "_detect_liquidity_sweep",
    "evaluate",
]

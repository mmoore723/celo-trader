"""
strategies/bos_mss/__init__.py — Break of Structure / Market Structure Shift (BOS_MSS)

Fires on the LAST bar of today's data (call on every tick; let route_signals
pass a full session slice so the evaluator can read the most recent bar).

Entry conditions:
  • Price breaks above the last confirmed swing high (bullish BOS) with:
      - FVG confirmation (imbalance evidence within last 20 bars)
      - RVOL ≥ 1.5×
      - EMA50 price alignment (close > EMA50 for bullish, < for bearish)
      - VWAP alignment (close > VWAP for bullish, < for bearish)
  • Mirror for bearish BOS (break below last confirmed swing low).

Fixes vs. original strategy_router.py
──────────────────────────────────────
1. Per-ticker cooldown  — 20-min window (base.check_cooldown / register_cooldown)
2. MFE early-exit gate  — skips if price already > 1.5× ATR past the BOS level:
     bullish: close > prior_hi + 1.5 × ATR  → already ran, chasing
     bearish: close < prior_lo - 1.5 × ATR  → already ran, chasing

NOTE: this strategy is DISABLED at the router level (see
strategy_router/__init__.py's docstring) — its sweep detection was merged
into FVG as a confidence modifier. Still imported by strategy_router/
evaluators.py (kept importable so nothing breaks if it's ever re-enabled),
just absent from ACTIVE_STRATEGIES.

Split (2026-08-01, file-size cleanup) out of the old single
strategies/bos_mss.py into constants.py, confidence.py, and evaluate.py;
no logic changed, only relocated. No external monkey-patching found for
this module (confirmed via a full-repo grep before the split), so this
__init__.py's re-exports are plain convenience imports.
"""

from strategies.bos_mss.constants import STRATEGY_ID, _MIN_BARS, _RVOL_FLOOR
from strategies.bos_mss.confidence import _compute_confidence
from strategies.bos_mss.evaluate import evaluate

__all__ = [
    "STRATEGY_ID",
    "_MIN_BARS",
    "_RVOL_FLOOR",
    "_compute_confidence",
    "evaluate",
]

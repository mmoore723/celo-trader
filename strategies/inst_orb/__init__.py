"""
strategies/inst_orb/ — Institutional Opening Range Breakout (INST_ORB)

Split from the old single strategies/inst_orb.py into themed modules
(2026-08-01, file-size cleanup) — no logic changed anywhere, only relocated.
This __init__.py re-exports the exact same public (and externally-read
mutable-state) names the old flat module did, so every existing
`from strategies import inst_orb` / `strategies.inst_orb.X` call site
elsewhere in the app is unaffected:

  constants.py — STRATEGY_ID, session-window timing, retest tolerances
  state.py      — _retest_state, _recent_expirations (mutated in place by
                  evaluate.py, so this re-export shares the same dict
                  objects — reads from api/routes/signals.py and
                  api/routes/tickers.py see live updates exactly as before)
  confidence.py  — _compute_confidence
  evaluate.py     — evaluate() (kept as one function, see its own docstring)

Session window : 09:45 – 10:30 ET (extended to 10:45 for retest entries)

Entry logic — RETEST SEQUENCE (not raw breakout):
  Phase 1 — BREAKOUT DETECTED: first bar that closes outside the OR boundary.
             We do NOT enter here. We wait.
  Phase 2 — RETEST IN PROGRESS: price pulls back and the candle's low (bullish)
             or high (bearish) touches the OR boundary ± tolerance.
  Phase 3 — BOUNCE CONFIRMED: after touching the OR level, price closes back
             through it. This bar is the entry.

State machine (per ticker per day):
  idle → breakout_seen → retesting → (entry fires) → idle
"""

from strategies.inst_orb.constants import (
    STRATEGY_ID, _SESSION_START, _BREAKOUT_DEADLINE, _SESSION_END,
    _RETEST_TOLERANCE_PCT, _RETEST_TOLERANCE_MIN,
)
from strategies.inst_orb.state import (
    _retest_state, _recent_expirations, _EXPIRATION_MEMORY_SEC, _get_state,
)
from strategies.inst_orb.confidence import _compute_confidence
from strategies.inst_orb.evaluate import evaluate

__all__ = [
    "STRATEGY_ID", "evaluate",
    "_retest_state", "_recent_expirations",
    "_get_state", "_compute_confidence",
]

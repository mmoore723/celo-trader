"""
strategies/base/__init__.py — shared primitives for all strategy evaluators.

Contents
────────
  Signal                     — dataclass returned by every evaluator
  MarketStructureAnalyzer    — 5-bar swing detection + trend classification
  _get_dynamic_rvol_threshold — context-aware RVOL gate
  _rvol_threshold_reason     — audit-log companion (plain-English reason)
  _has_recent_fvg            — Fair Value Gap scanner helper
  _find_swings               — 2-bar pivot helper (dashboard chart overlays only)
  _signal_cooldown           — module-level dict: tracks last fire time per strategy+ticker
  SIGNAL_COOLDOWN_MINUTES    — minimum gap between same-strategy signals on same ticker

Split (2026-08-01, file-size cleanup) out of the old single
strategies/base.py into signal.py, market_structure.py, rvol_threshold.py,
fvg.py, swings.py, and cooldown.py; no logic changed, only relocated.
Re-exports every public name so every existing `from strategies.base
import X` call site across the app keeps working unchanged. See
cooldown.py's module docstring for why `_signal_cooldown` specifically
must be re-exported by reference, not by value.
"""

from __future__ import annotations

from strategies.base.signal import Signal
from strategies.base.market_structure import MarketStructureAnalyzer
from strategies.base.rvol_threshold import _get_dynamic_rvol_threshold, _rvol_threshold_reason
from strategies.base.fvg import _has_recent_fvg
from strategies.base.swings import _find_swings
from strategies.base.cooldown import (
    _signal_cooldown, SIGNAL_COOLDOWN_MINUTES, check_cooldown, register_cooldown,
)

__all__ = [
    "Signal",
    "MarketStructureAnalyzer",
    "_get_dynamic_rvol_threshold", "_rvol_threshold_reason",
    "_has_recent_fvg",
    "_find_swings",
    "_signal_cooldown", "SIGNAL_COOLDOWN_MINUTES",
    "check_cooldown", "register_cooldown",
]

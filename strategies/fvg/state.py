"""
strategies/fvg/state.py — _consumed_gaps: per-session gap dedup set.

Split out of the old single strategies/fvg.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.

Track gaps that have already triggered a signal (ticker, date, gap_low,
gap_high). Once a gap fires, it's consumed for the session — the same
imbalance zone cannot fire again even if price re-enters it.

This set is mutated IN PLACE (.add(), .difference_update()) by evaluate.py,
never reassigned — same safe-re-export pattern as strategies/base/
cooldown.py's _signal_cooldown dict, confirmed with no external consumers
of this name (only used internally within the fvg package).
"""

_consumed_gaps: set[tuple] = set()

"""
strategies/ifvg/state.py — _consumed_ifvgs: per-session inverted-zone dedup set.

Split out of the old single strategies/ifvg.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.

Session-scoped deduplication set — keyed separately from FVG's
_consumed_gaps set so both strategies can coexist on the same underlying
zone without interfering. Mutated IN PLACE by evaluate.py, never
reassigned — no external consumers found via grep, so the plain re-export
in __init__.py keeps identical object identity everywhere.
"""

_consumed_ifvgs: set[tuple] = set()

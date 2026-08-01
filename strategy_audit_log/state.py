"""
strategy_audit_log/state.py — dedup state so structural/RVOL narration only
fires on actual change, not every bar.

Split out of the old single strategy_audit_log.py (2026-08-01, file-size
cleanup); no logic changed, only relocated. Mutated in place (dict item
assignment) everywhere it's touched, never reassigned wholesale — so a
normal re-export from __init__.py preserves identity, no live dotted
lookup trick needed.
"""
from __future__ import annotations

_last_audit_state: dict = {}

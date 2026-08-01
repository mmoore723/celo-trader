"""
strategy_audit_log/ — Plain-English structural/decision audit logger.

Extracted from strategy_router.py (2026-07-16) to keep the router itself
under ~200 lines. Writes human-readable narration to system_events so the
dashboard can show WHY the bot did or didn't take a trade, without needing
to read raw signal/confidence numbers. Fires only on structural change or
RVOL-tier change to avoid spamming the DB every single bar.

Split further out of the old single strategy_audit_log.py (2026-08-01,
file-size cleanup) into:
  - constants.py: _STRAT_NAMES
  - state.py:     _last_audit_state (mutated in place, never reassigned)
  - messages.py:  per-section plain-English message builders
  - audit.py:     audit_plain_english(), the public entry point

No monkeypatching of this module's names was found anywhere in the
codebase (grep-verified), so this __init__.py just re-exports normally.
"""
from __future__ import annotations

from strategy_audit_log.audit import audit_plain_english
from strategy_audit_log.constants import _STRAT_NAMES
from strategy_audit_log.state import _last_audit_state

__all__ = [
    "audit_plain_english",
]

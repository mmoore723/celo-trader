"""
strategies/inst_orb/state.py — Per-ticker-per-day retest state machine
(_retest_state) and the read-only expiration side-channel for the
dashboard's Watching tab (_recent_expirations).

Split out of the old single strategies/inst_orb.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.

Both dicts are mutated in place (never reassigned) by evaluate.py, so the
same object is shared correctly across every importer, including external
code that reads strategies.inst_orb._retest_state / _recent_expirations
directly (api/routes/signals.py, api/routes/tickers.py) -- re-exporting a
reference to these dicts via __init__.py preserves that shared-object
semantics exactly like the flat module did.
"""

from datetime import date as _date

# Per-ticker, per-day retest state machine.
# Key: (ticker, date_str)  Value: phase dict
_retest_state: dict[tuple[str, str], dict] = {}

# 2026-07-28: read-only side-channel for the dashboard's Watching tab.
# _retest_state gets fully wiped and rebuilt on every evaluate() call (see
# the comment above evaluate()'s reset block) — that's correct for the
# state machine itself, but it means a setup that WAS mid-retest a moment
# ago just silently vanishes from the API with no trace of what happened
# to it. This dict remembers, for a short window, whether a vanished setup
# expired (gave up — bounce failed, gate blocked it, etc.) so the UI can
# say "expired" instead of just disappearing. Never read by the state
# machine itself — purely observational.
_recent_expirations: dict[tuple[str, str], dict] = {}
_EXPIRATION_MEMORY_SEC = 300   # how long a card stays visible as "expired"


def _get_state(ticker: str, today_date: _date) -> dict:
    """Return (and lazily initialize) the retest state for ticker+date."""
    key = (ticker, today_date.isoformat())
    if key not in _retest_state:
        _retest_state[key] = {
            "phase":       "idle",      # idle | breakout_seen | retesting
            "direction":   None,        # "bullish" | "bearish"
            "or_boundary": None,        # the OR level price must retest
            "breakout_bar":None,        # timestamp of the breakout bar (for logging)
            "retest_bar":  None,        # timestamp of the retest touch bar
        }
    # Prune stale state from prior days (keep only today + yesterday)
    stale = [k for k in _retest_state if k[1] < today_date.isoformat()]
    for k in stale:
        del _retest_state[k]
    return _retest_state[key]

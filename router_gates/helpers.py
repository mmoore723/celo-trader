"""
router_gates/helpers.py — Shared signal_journal 'blocked' row writer used
by every hard-block gate in this package.

Split out of the old single router_gates.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""

from signal_journal import log_signal_outcome as _log_journal


def _journal_dropped(before: list, after: list, ticker: str, reason_code: str, reason_detail: str = "") -> None:
    """
    Write one signal_journal 'blocked' row per signal a gate just removed.
    Shared by every hard-block gate below so the diff logic lives in one
    place — compares by id() since signal objects aren't hashable/comparable.
    """
    _after_ids = {id(s) for s in after}
    for _s in before:
        if id(_s) in _after_ids:
            continue
        try:
            _log_journal(ticker, _s.strategy_id, _s.direction, _s.confidence,
                         outcome="blocked", reason_code=reason_code, reason_detail=reason_detail,
                         context={"trigger_bar": str(_s.trigger_bar), "strategy_meta": _s.meta},
                         tier=getattr(_s, "tier", "main"))
        except Exception:
            pass   # journal writes are never allowed to affect gate behavior

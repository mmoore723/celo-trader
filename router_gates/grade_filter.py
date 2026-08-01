"""
router_gates/grade_filter.py — Gate 5b: minimum-grade filter (OFF by
default), mirroring the dashboard's premarket A+/A/B/C/Watch grading.

Split out of the old single router_gates.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.

2026-07-24: the dashboard's premarket report already grades every ticker
A+/A/B/C/Watch (api/routes/market.py::_grade()) but that grade was DISPLAY
ONLY — never read by live entry logic, so a "Watch"-grade ticker with no
real setup could still fire a real trade if it happened to pass a
strategy's own internal gates. This mirrors that same grading formula so a
blocked entry matches what the dashboard shows, and blocks entries below a
configurable minimum grade (default cutoff "C" — only "Watch" is blocked).

KNOWN FIDELITY GAP: this uses strategy_router's own rvol (compute_rvol(),
10-day lookback) and atr, not market.py's separately-computed time-
normalized live rvol — the two methods can disagree slightly since they're
genuinely different calculations. Exact parity would require unifying both
call sites onto one shared rvol function; out of scope for this gate.
"""

import logging

import pandas as pd

from database import log_event as _db_log
from config import get_settings as _get_settings
from scanner import _ETF_SET as _GRADE_ETF_SET
from router_gates.helpers import _journal_dropped

logger = logging.getLogger("celo_trader.router_gates")

_GRADE_ORDER = {"Watch": 0, "C": 1, "B": 2, "A": 3, "A+": 4}


def _grade_from_metrics(gap_pct: float, rvol: float, atr: float, is_etf: bool) -> str:
    """Mirrors api/routes/market.py::_grade() — keep both in sync if either changes."""
    ag   = abs(gap_pct)
    gmin = 0.5 if is_etf else 1.0
    if ag >= 2.0 and rvol >= 2.5 and atr >= 1.5:
        return "A+"
    if ag >= gmin and rvol >= 2.0 and atr >= 1.0:
        return "A"
    if ag >= gmin * 0.5 and rvol >= 1.5:
        return "B"
    if ag >= gmin * 0.25:
        return "C"
    return "Watch"


def apply_grade_filter(signals: list, today: pd.DataFrame, ticker: str, quiet: bool = False) -> list:
    if not signals or len(today) == 0:
        return signals
    _s = _get_settings()
    if not bool(_s.get("min_grade_filter_enabled", False)):
        return signals
    _min_grade = str(_s.get("min_entry_grade", "C"))
    if _min_grade not in _GRADE_ORDER:
        _min_grade = "C"

    _last = today.iloc[-1]
    _gap  = float(_last.get("session_gap_pct", 0.0) or 0.0)
    _rvol = float(_last.get("rvol", 0.0) or 0.0)
    _atr  = float(_last.get("atr", 0.0) or 0.0)
    _grade = _grade_from_metrics(_gap, _rvol, _atr, ticker in _GRADE_ETF_SET)

    if _GRADE_ORDER[_grade] >= _GRADE_ORDER[_min_grade]:
        return signals

    if not quiet:
        _journal_dropped(signals, [], ticker, "grade_filter",
                          f"{_grade} grade below minimum {_min_grade} "
                          f"(gap={_gap:+.2f}%, rvol={_rvol:.1f}x, atr=${_atr:.2f})")
        _db_log("INFO", "bar_eval",
                f"⚪ [{ticker}] Grade filter: {_grade} setup (gap={_gap:+.2f}%, "
                f"rvol={_rvol:.1f}x, atr=${_atr:.2f}) below minimum {_min_grade} "
                f"— {len(signals)} entry signal(s) blocked.")
        logger.info("router: grade filter blocked %s (%s < %s)", ticker, _grade, _min_grade)
    return []

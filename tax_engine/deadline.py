"""
tax_engine/deadline.py — next_tax_deadline(): quarterly estimated tax
payment reminder.

Split out of the old single tax_engine.py (2026-08-01, file-size cleanup);
no logic changed, only relocated.
"""

from datetime import date
from typing import Optional

# ── Quarterly estimated tax reminder ─────────────────────────────────────────

QUARTERLY_DEADLINES = [
    (4, 15,  "Q1 estimated tax due (Jan–Mar income)"),
    (6, 17,  "Q2 estimated tax due (Apr–May income)"),
    (9, 16,  "Q3 estimated tax due (Jun–Aug income)"),
    (1, 15,  "Q4 estimated tax due (Sep–Dec income)"),  # next year Jan 15
]

def next_tax_deadline() -> Optional[dict]:
    """Return the next upcoming quarterly estimated tax deadline."""
    today = date.today()
    for month, day, label in QUARTERLY_DEADLINES:
        year = today.year if month >= today.month else today.year + 1
        deadline = date(year, month, day)
        if deadline >= today:
            days_away = (deadline - today).days
            return {
                "date":      deadline.isoformat(),
                "label":     label,
                "days_away": days_away,
                "urgent":    days_away <= 30,
            }

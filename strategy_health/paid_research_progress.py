"""Read-only, report-backed progress for in-flight paid-data research.

This module deliberately exposes progress and a provisional leader only.  It
does not decide whether a strategy may trade; that requires the separate
completed-study robustness review.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
TREND_EXIT_REPORT = _PROJECT_ROOT / "reports" / "paid_tsla_trend_exit_holds.json"


def tsla_trend_exit_progress(report_path: Path = TREND_EXIT_REPORT) -> dict[str, Any]:
    """Return a safe, human-readable view of the current TSLA trend study."""
    unavailable = {
        "available": False,
        "study_id": "paid_tsla_trend_exit_holds",
        "label": "TSLA Trend Continuation — exit study",
        "note": "No saved study report is available on this server yet.",
    }
    try:
        raw = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return unavailable
    if not isinstance(raw, dict):
        return unavailable

    processed_files = raw.get("processed_files")
    processed = len(processed_files) if isinstance(processed_files, list) else 0
    total = raw.get("candidate_files")
    total = int(total) if isinstance(total, int) and total >= 0 else 0
    complete = bool(raw.get("complete")) and total > 0 and processed >= total
    selection = raw.get("selection") if isinstance(raw.get("selection"), dict) else {}
    selected = selection.get("selected_hold_minutes")
    selected = int(selected) if isinstance(selected, int) and selected > 0 else None
    selected_summary = {}
    summaries = selection.get("summaries")
    if selected is not None and isinstance(summaries, dict):
        possible = summaries.get(str(selected))
        if isinstance(possible, dict):
            selected_summary = possible
    holdout = selected_summary.get("holdout") if isinstance(selected_summary.get("holdout"), dict) else {}
    holdout_count = holdout.get("measured_signals")
    holdout_count = int(holdout_count) if isinstance(holdout_count, int) and holdout_count >= 0 else 0

    if complete:
        status = "review_pending"
        decision = "The quote study is complete. A separate robustness review must still approve or reject paper trading."
    elif holdout_count:
        status = "testing_new_dates"
        decision = "The study is now checking newer dates that were not used to choose the exit. It is still not eligible to trade."
    else:
        status = "testing_exit_clock"
        decision = "The study is comparing 30-, 60-, and 90-minute exits on earlier data. The current leader is provisional."

    return {
        "available": True,
        "study_id": "paid_tsla_trend_exit_holds",
        "label": "TSLA Trend Continuation — exit study",
        "ticker": str(raw.get("ticker") or "TSLA").upper(),
        "strategy": str(raw.get("strategy") or "trend_continuation"),
        "complete": complete,
        "status": status,
        "processed_days": processed,
        "total_days": total,
        "progress_pct": round(processed / total * 100, 1) if total else 0.0,
        "provisional_exit_minutes": selected,
        "holdout_signals_seen": holdout_count,
        "decision": decision,
        "note": "Uses purchased historical option quotes: entry at ask and exit at the same contract's bid. It never sends an order or changes bot settings.",
    }

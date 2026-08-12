#!/usr/bin/env python3
"""Tune a small morning-momentum-to-close hypothesis without look-ahead.

At 10:00 ET the first six five-minute bars are complete.  A candidate enters
at that bar's open and exits at 15:55.  Only the earliest calibration period
may choose a configuration; the following year decides whether it survives.
The final period is printed for transparency but is already observational in
this research programme and cannot authorize trading.  This is underlying
research only: no options, broker, order, or sizing capability exists here.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, time
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.engine.data import load_csv


OPENING_SLOTS = (time(9, 30), time(9, 35), time(9, 40), time(9, 45), time(9, 50), time(9, 55))
ENTRY_TIME, EXIT_TIME = time(10, 0), time(15, 55)
MIN_MOVES = (0.0010, 0.0020, 0.0025, 0.0035, 0.0050)
DIRECTIONS = ("both", "calls_only", "puts_only")


@dataclass(frozen=True)
class Candidate:
    min_opening_move_pct: float
    direction: str


def _summary(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"trades": 0, "win_rate_pct": None, "average_return_pct": None, "total_return_pct": None}
    return {
        "trades": len(values),
        "win_rate_pct": round(sum(value > 0 for value in values) * 100 / len(values), 1),
        "average_return_pct": round(mean(values) * 100, 4),
        "total_return_pct": round(sum(values) * 100, 4),
    }


def _returns(path: Path) -> list[tuple[datetime, float, int, float]]:
    by_day: dict[object, dict[time, object]] = defaultdict(dict)
    for bar in load_csv(path).bars:
        by_day[bar.timestamp.date()][bar.timestamp.time()] = bar
    rows: list[tuple[datetime, float, int]] = []
    for session in by_day.values():
        opening = [session.get(slot) for slot in OPENING_SLOTS]
        entry, exit_ = session.get(ENTRY_TIME), session.get(EXIT_TIME)
        if any(bar is None for bar in opening) or entry is None or exit_ is None:
            continue
        assert entry is not None and exit_ is not None
        move = (opening[-1].close - opening[0].open) / opening[0].open
        forward = (exit_.open - entry.open) / entry.open
        rows.append((entry.timestamp, move, 1 if move > 0 else -1 if move < 0 else 0, forward))
    return rows


def _evaluate(rows: list[tuple], candidate: Candidate) -> list[float]:
    values: list[float] = []
    threshold = candidate.min_opening_move_pct / 100
    for _, move, side, forward in rows:
        if abs(move) < threshold:
            continue
        if candidate.direction == "calls_only" and side != 1:
            continue
        if candidate.direction == "puts_only" and side != -1:
            continue
        values.append(side * forward)
    return values


def _passes(summary: dict) -> bool:
    return (summary["trades"] >= 40 and summary["win_rate_pct"] is not None
            and summary["win_rate_pct"] >= 50.0 and summary["average_return_pct"] is not None
            and summary["average_return_pct"] > 0.0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="append", required=True, metavar="TICKER=CSV")
    parser.add_argument("--calibration-end", required=True, help="ISO timestamp; earliest period ends here")
    parser.add_argument("--validation-end", required=True, help="ISO timestamp; validation ends here")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    calibration_end = datetime.fromisoformat(args.calibration_end.replace("Z", "+00:00"))
    validation_end = datetime.fromisoformat(args.validation_end.replace("Z", "+00:00"))
    if validation_end <= calibration_end:
        parser.error("validation end must be after calibration end")
    candidates = [Candidate(round(move * 100, 2), direction) for move in MIN_MOVES for direction in DIRECTIONS]
    symbols: dict[str, dict] = {}
    for item in args.input:
        if "=" not in item:
            parser.error("--input must be TICKER=CSV")
        ticker, raw_path = item.split("=", 1)
        rows = _returns(Path(raw_path))
        calibration = [row for row in rows if row[0] < calibration_end]
        validation = [row for row in rows if calibration_end <= row[0] < validation_end]
        observational_final = [row for row in rows if row[0] >= validation_end]
        all_results = []
        for candidate in candidates:
            calibration_summary = _summary(_evaluate(calibration, candidate))
            validation_summary = _summary(_evaluate(validation, candidate))
            all_results.append({"candidate": asdict(candidate), "calibration": calibration_summary,
                                "validation": validation_summary,
                                "eligible": _passes(calibration_summary) and _passes(validation_summary)})
        # Selection is based exclusively on pre-final data.  Rank stable return
        # first, then total validation evidence; do not use the final period.
        survivors = [row for row in all_results if row["eligible"]]
        survivors.sort(key=lambda row: (row["validation"]["average_return_pct"], row["validation"]["trades"]), reverse=True)
        selected = survivors[0] if survivors else None
        if selected:
            chosen = Candidate(**selected["candidate"])
            selected = {**selected, "observational_final": _summary(_evaluate(observational_final, chosen)),
                        "final_period_notice": "Already viewed in earlier horizon exploration; cannot authorize promotion."}
        symbols[ticker.upper().strip()] = {
            "calibration_rows": len(calibration), "validation_rows": len(validation), "observational_final_rows": len(observational_final),
            "selected_from_pre_final_only": selected, "all_pre_final_results": all_results,
        }
    payload = {
        "purpose": "Pre-final tuning of a morning-momentum-to-close underlying hypothesis; no options or trading authorization.",
        "fixed_design": {"decision_time": "10:00 open", "exit_time": "15:55 open", "opening_window": "09:30-10:00 ET",
                         "minimum_move_grid_pct": [move * 100 for move in MIN_MOVES], "direction_grid": list(DIRECTIONS),
                         "minimum_evidence": "At least 40 trades, positive average return, and >=50% win rate in both calibration and validation."},
        "calibration_end": calibration_end.isoformat(), "validation_end": validation_end.isoformat(), "symbols": symbols,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()

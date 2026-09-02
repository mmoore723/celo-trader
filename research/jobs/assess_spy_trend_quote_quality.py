#!/usr/bin/env python3
"""Evaluate causal quote-quality gates for reviewed SPY Trend entries.

This reuses completed, already-paid contract markouts.  It does not alter the
signal, contract, entry clock, exit, or sizing.  A candidate may only decline
an entry using fields visible when the contract was selected.  The variants
and gates are intentionally frozen and sparse so this is not threshold mining.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime
import json
from pathlib import Path
import statistics
import sys
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.jobs.compare_paid_contract_selection import summary


BASELINE = "all_reviewed_quotes"
MIN_TRAINING_TRADES = 20
MIN_LATER_TRADES = 20
MIN_COVERAGE = .80


# All values are known at the contract decision time.  Spread is represented
# as a decimal in the source report (.0065 == .65%).  These are execution-risk
# envelopes, not fitted signal indicators.
GATES: dict[str, Callable[[dict[str, object]], bool]] = {
    BASELINE: lambda _row: True,
    "spread_at_most_65bp": lambda row: float(row["spread_pct"]) <= .0065,
    "spread_at_most_75bp": lambda row: float(row["spread_pct"]) <= .0075,
    "spread_65bp_and_premium_4": lambda row: (
        float(row["spread_pct"]) <= .0065 and float(row["entry_ask"]) >= 4.0
    ),
    "spread_65bp_and_near_money": lambda row: (
        float(row["spread_pct"]) <= .0065
        and float(row["moneyness_pct"]) <= .0015
    ),
}


def split(rows: list[dict[str, object]], cutoff: date) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    early, later = [], []
    for row in rows:
        target = early if datetime.fromisoformat(str(row["signal_time"])).date() < cutoff else later
        target.append(row)
    return early, later


def _pf(value: object) -> float:
    if value == "no_losses" or value is None:
        return float("inf") if value == "no_losses" else 0.0
    return float(value)


def _candidate_passes(
    candidate: dict[str, object], baseline: dict[str, object],
    candidate_count: int, baseline_count: int, minimum_trades: int,
) -> bool:
    coverage = candidate_count / baseline_count if baseline_count else 0.0
    return (
        candidate_count >= minimum_trades
        and coverage >= MIN_COVERAGE
        and float(candidate.get("average_return_pct") or 0) > 0
        and float(candidate.get("median_return_pct") or 0) > 0
        and _pf(candidate.get("profit_factor")) >= 1.20
        and float(candidate.get("max_drawdown_at_cap") or 0)
        <= max(1.0, float(baseline.get("max_drawdown_at_cap") or 0) * .90)
    )


def evaluate(rows: list[dict[str, object]], cutoff: date) -> dict[str, object]:
    early, later = split(rows, cutoff)
    baseline_early, baseline_later = summary(early), summary(later)
    table: dict[str, object] = {}
    eligible: list[tuple[float, float, float, str]] = []

    for gate_id, gate in GATES.items():
        gate_early = [row for row in early if gate(row)]
        gate_later = [row for row in later if gate(row)]
        early_summary, later_summary = summary(gate_early), summary(gate_later)
        early_coverage = len(gate_early) / len(early) if early else 0.0
        later_coverage = len(gate_later) / len(later) if later else 0.0
        table[gate_id] = {
            "selection": early_summary,
            "selection_coverage": round(early_coverage, 4),
            "later": later_summary,
            "later_coverage": round(later_coverage, 4),
        }
        if gate_id != BASELINE and _candidate_passes(
            early_summary, baseline_early, len(gate_early), len(early), MIN_TRAINING_TRADES
        ):
            eligible.append((
                _pf(early_summary.get("profit_factor")),
                float(early_summary.get("median_return_pct") or 0),
                -float(early_summary.get("max_drawdown_at_cap") or 0),
                gate_id,
            ))

    selected = max(eligible)[-1] if eligible else None
    later_passed = False
    if selected:
        selected_later = table[selected]["later"]
        later_count = int(selected_later["trades"])
        later_passed = _candidate_passes(
            selected_later, baseline_later, later_count, len(later), MIN_LATER_TRADES
        ) and (
            float(selected_later["total_pnl_at_cap"])
            > float(baseline_later["total_pnl_at_cap"])
        )

    return {
        "complete": True,
        "methodology": (
            "Frozen causal quote gates on nearest-expiry SPY Trend V2 entries; "
            "pre-July selects once and July is revealed once. Signal, contract, "
            "entry ask, 30-minute bid exit, and capped sizing are unchanged."
        ),
        "cutoff": cutoff.isoformat(),
        "gate": {
            "minimum_selection_trades": MIN_TRAINING_TRADES,
            "minimum_later_trades": MIN_LATER_TRADES,
            "minimum_coverage": MIN_COVERAGE,
            "minimum_profit_factor": 1.20,
            "positive_average_and_median": True,
            "selection_drawdown_at_least_10pct_lower_than_baseline": True,
            "later_total_pnl_must_exceed_baseline": True,
        },
        "selected_gate": selected,
        "later_passed": later_passed,
        "decision": "promote_quote_quality_gate" if later_passed else "retain_unfiltered_reviewed_entries",
        "results": table,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cutoff", type=date.fromisoformat, default=date(2026, 7, 1))
    args = parser.parse_args()
    source = json.loads(args.input.read_text())
    rows = list(source["results"]["nearest_expiry"])
    report = {
        "source": str(args.input),
        "strategy": source.get("strategy"),
        "ticker": source.get("ticker"),
        "source_rows": len(rows),
        **evaluate(rows, args.cutoff),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["decision"], indent=2))


if __name__ == "__main__":
    main()

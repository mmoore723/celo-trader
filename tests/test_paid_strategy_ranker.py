from datetime import date

from research.jobs.evaluate_paid_strategy_ranker import build_report


def _row(day: date, index: int, return_pct: float) -> dict:
    month = day.month
    return {
        "signal_time": f"{day.isoformat()}T10:{index % 60:02d}:00-04:00",
        "entry_time": f"{day.isoformat()}T14:{index % 60:02d}:30+00:00",
        "exit_time": f"{day.isoformat()}T14:{(index + 30) % 60:02d}:30+00:00",
        "contract": f"SPY   2608{20 + month:02d}C00700000",
        "entry_ask": 5.0 + index / 100,
        "exit_bid": (5.0 + index / 100) * (1 + return_pct / 100),
        "return_pct": return_pct,
        "underlying_entry": 700.0 + index / 10,
        "strategy_id": "V2_SPY_TREND_CONT",
    }


def test_strategy_ranker_keeps_holdout_out_of_model_selection():
    rows = []
    for month, count in ((5, 32), (6, 40), (7, 40)):
        for index in range(count):
            rows.append(_row(date(2026, month, 1 + index % 20), index, 3.0 if index % 2 else -2.0))
    first = build_report(rows, validation_start=date(2026, 6, 1), holdout_start=date(2026, 7, 1))
    selected = first["selected_retention_fraction"]
    for row in rows:
        if row["signal_time"].startswith("2026-07"):
            row["return_pct"] *= -10
            row["exit_bid"] = row["entry_ask"] * (1 + row["return_pct"] / 100)
    changed = build_report(rows, validation_start=date(2026, 6, 1), holdout_start=date(2026, 7, 1))
    assert changed["selected_retention_fraction"] == selected
    assert changed["segments"]["holdout_ranked"] != first["segments"]["holdout_ranked"]

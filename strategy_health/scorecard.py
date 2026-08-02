"""Read-only strategy scorecard built from paper/live decision and outcome data."""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from database import get_conn, _now_et


MIN_ACTIONABLE_TRADES = 20


def build_scorecard(days: int = 30) -> dict:
    """Combine closed-trade outcomes with signal blocks; never changes risk."""
    days = max(1, min(int(days), 365))
    cutoff = (_now_et() - timedelta(days=days)).isoformat()
    rows: dict[str, dict] = defaultdict(lambda: {
        "strategy_id": "UNKNOWN", "closed_trades": 0, "wins": 0,
        "pnl": 0.0, "blocked_signals": 0, "entered_signals": 0,
        "block_reasons": defaultdict(int),
    })
    with get_conn() as conn:
        trades = conn.execute(
            "SELECT strategy_id, realized_pnl FROM trades "
            "WHERE status='closed' AND exit_time >= ?", (cutoff,)
        ).fetchall()
        signals = conn.execute(
            "SELECT strategy_id, outcome, reason_code FROM signal_journal WHERE ts >= ?",
            (cutoff,),
        ).fetchall()
    for trade in trades:
        sid = trade["strategy_id"] or "UNKNOWN"
        row = rows[sid]; row["strategy_id"] = sid
        pnl = float(trade["realized_pnl"] or 0.0)
        row["closed_trades"] += 1; row["pnl"] += pnl
        row["wins"] += int(pnl > 0)
    for signal in signals:
        sid = signal["strategy_id"] or "UNKNOWN"
        row = rows[sid]; row["strategy_id"] = sid
        if signal["outcome"] == "entered":
            row["entered_signals"] += 1
        else:
            row["blocked_signals"] += 1
            row["block_reasons"][signal["reason_code"] or "unknown"] += 1
    result = []
    for row in rows.values():
        n = row["closed_trades"]
        row["pnl"] = round(row["pnl"], 2)
        row["win_rate"] = round(row["wins"] / n * 100, 1) if n else None
        row["expectancy"] = round(row["pnl"] / n, 2) if n else None
        row["sample_status"] = "actionable" if n >= MIN_ACTIONABLE_TRADES else "collecting_data"
        row["block_reasons"] = dict(sorted(row["block_reasons"].items(), key=lambda x: -x[1]))
        result.append(dict(row))
    result.sort(key=lambda r: (r["sample_status"] != "actionable", -r["pnl"]))
    return {"days": days, "minimum_actionable_trades": MIN_ACTIONABLE_TRADES, "strategies": result}

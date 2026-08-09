"""Read-only prospective evidence for the paid-study-aligned V2 paper pilot."""
from __future__ import annotations

from typing import Any

from database import get_conn


V2_ORB_STRATEGY_ID = "V2_ORB_PULLBACK"
MIN_PROSPECTIVE_REVIEW_TRADES = 20


def build_v2_orb_paper_scorecard(*, broker_account_id: str | None) -> dict[str, Any]:
    """Report V2 paper outcomes without blending accounts or strategies.

    This is evidence only.  It cannot change sizing, enable a strategy, or
    place an order.  An exit is called ``study_matched`` only when it used the
    V2 fixed-90-minute paper exit, making any deviation visible rather than
    accidentally calling it support for the paid historical study.
    """
    clauses = ["strategy_id = ?", "paper = 1"]
    params: list[object] = [V2_ORB_STRATEGY_ID]
    if broker_account_id:
        clauses.append("broker_account_id = ?")
        params.append(broker_account_id)
    else:
        clauses.append("(broker_account_id IS NULL OR broker_account_id = '')")
    where = " AND ".join(clauses)
    with get_conn() as conn:
        row = conn.execute(
            """SELECT
                   COUNT(*) AS entered,
                   SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END) AS open_trades,
                   SUM(CASE WHEN status = 'closed' THEN 1 ELSE 0 END) AS closed_trades,
                   SUM(CASE WHEN status = 'closed' AND realized_pnl > 0 THEN 1 ELSE 0 END) AS wins,
                   SUM(CASE WHEN status = 'closed' THEN realized_pnl ELSE 0 END) AS pnl,
                   AVG(CASE WHEN status = 'closed' AND entry_price > 0
                            THEN (exit_price - entry_price) / entry_price * 100 END) AS average_return_pct,
                   SUM(CASE WHEN status = 'closed' AND exit_reason LIKE 'v2_orb_paid_markout_90m%' THEN 1 ELSE 0 END) AS study_matched_exits,
                   SUM(CASE WHEN status = 'closed' AND (exit_reason IS NULL OR exit_reason NOT LIKE 'v2_orb_paid_markout_90m%') THEN 1 ELSE 0 END) AS nonmatching_exits
               FROM trades WHERE """ + where,
            tuple(params),
        ).fetchone()

    closed = int(row["closed_trades"] or 0)
    wins = int(row["wins"] or 0)
    matched = int(row["study_matched_exits"] or 0)
    nonmatching = int(row["nonmatching_exits"] or 0)
    return {
        "strategy_id": V2_ORB_STRATEGY_ID,
        "broker_account_id": broker_account_id,
        "account_scoped": bool(broker_account_id),
        "entered": int(row["entered"] or 0),
        "open_trades": int(row["open_trades"] or 0),
        "closed_trades": closed,
        "wins": wins,
        "win_rate_pct": round(wins * 100 / closed, 1) if closed else None,
        "pnl": round(float(row["pnl"] or 0.0), 2),
        "average_return_pct": round(float(row["average_return_pct"]), 4)
        if row["average_return_pct"] is not None else None,
        "study_matched_exits": matched,
        "nonmatching_exits": nonmatching,
        "minimum_review_trades": MIN_PROSPECTIVE_REVIEW_TRADES,
        "sample_status": "review_ready" if closed >= MIN_PROSPECTIVE_REVIEW_TRADES and nonmatching == 0 else "collecting_data",
        "note": "This is prospective paper evidence only. It uses actual recorded paper fills; commissions and future slippage are not included in this scorecard.",
    }

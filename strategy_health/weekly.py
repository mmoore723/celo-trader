"""
strategy_health/weekly.py — rolls the trailing week of daily strategy_health
audits AND real executed trades into one bigger-picture view.

Why this exists (2026-07-20): the daily audit (engine.py/runner.py) looks at
ONE trading day in isolation — it can't see a week-over-week pattern, and it
never touches the risk-math side (R:R gate vs. realized win/loss, stop
schedule vs. actual held time) at all. This module closes both gaps by
reusing data that already exists rather than re-deriving it:
  1. Sums the per-strategy funnel numbers (raw signals / router survivors /
     actual trades) across the last N saved daily audits (strategy_audits,
     audit_type='daily') — no new market-data fetching needed.
  2. Reads the real `trades` table directly for the same window and computes
     the same expectancy/win-rate/exit-reason/held-time cross-check
     diag_risk_math.py did by hand — but from actual executed trades, not a
     backtest replay, and it runs on a schedule instead of someone remembering
     to run a script.
Nothing here recommends or applies a code change — see ai_narrator.py's
weekly prompt for the hard "always A/B test first" constraint.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import date, timedelta

from database import get_conn

logger = logging.getLogger("celo_trader.strategy_health.weekly")


def _iso_week_label(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def _sum_daily_funnels(days: int = 7) -> tuple[dict, list[str]]:
    """Sum per-strategy funnel stats across the last `days` calendar days of
    saved daily audits. Returns (per_strategy_funnel, audit_dates_included)."""
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT audit_date, aggregate_json FROM strategy_audits "
            "WHERE audit_type = 'daily' AND audit_date >= ? ORDER BY audit_date",
            (cutoff,),
        ).fetchall()

    per_strategy: dict = defaultdict(lambda: {
        "raw_signals": 0, "router_survivors": 0,
        "worked_raw": 0, "worked_survivors": 0,
        "actual_trades": 0, "actual_wins": 0, "actual_pnl": 0.0,
    })
    dates_included: list[str] = []
    for row in rows:
        dates_included.append(row["audit_date"])
        try:
            agg = json.loads(row["aggregate_json"])
        except Exception:
            continue
        for sid, funnel in (agg.get("per_strategy") or {}).items():
            dst = per_strategy[sid]
            for key in ("raw_signals", "router_survivors", "worked_raw",
                        "worked_survivors", "actual_trades", "actual_wins"):
                dst[key] += int(funnel.get(key, 0) or 0)
            dst["actual_pnl"] += float(funnel.get("actual_pnl", 0.0) or 0.0)

    return dict(per_strategy), dates_included


def _risk_math_from_real_trades(days: int = 7) -> dict:
    """
    Real-trade expectancy + risk-math cross-check for the trailing window —
    same question diag_risk_math.py answered by hand, computed here from the
    actual `trades` table (real fills, not a backtest replay).
    """
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT strategy_id, realized_pnl, exit_reason, entry_time, exit_time "
            "FROM trades WHERE status = 'closed' AND substr(entry_time,1,10) >= ?",
            (cutoff,),
        ).fetchall()

    per_strategy: dict = defaultdict(lambda: {
        "n": 0, "wins": 0, "total_pnl": 0.0, "win_pnls": [], "loss_pnls": [],
        "exit_reasons": defaultdict(int),
    })
    for r in rows:
        sid = r["strategy_id"] or "UNKNOWN"
        pnl = float(r["realized_pnl"] or 0.0)
        d = per_strategy[sid]
        d["n"] += 1
        d["total_pnl"] += pnl
        if pnl > 0:
            d["wins"] += 1
            d["win_pnls"].append(pnl)
        else:
            d["loss_pnls"].append(pnl)
        # exit_reason strings carry parenthetical detail (e.g. "held=22.7min") —
        # bucket on the prefix before the first "(" so the mix stays readable.
        reason = (r["exit_reason"] or "unknown").split(" (")[0]
        d["exit_reasons"][reason] += 1

    result = {}
    for sid, d in per_strategy.items():
        n = d["n"]
        avg_win  = sum(d["win_pnls"]) / len(d["win_pnls"]) if d["win_pnls"] else 0.0
        avg_loss = sum(d["loss_pnls"]) / len(d["loss_pnls"]) if d["loss_pnls"] else 0.0
        result[sid] = {
            "n":            n,
            "win_rate_pct": round(d["wins"] / n * 100, 1) if n else 0.0,
            "avg_pnl":      round(d["total_pnl"] / n, 2) if n else 0.0,
            "total_pnl":    round(d["total_pnl"], 2),
            "avg_win":      round(avg_win, 2),
            "avg_loss":     round(avg_loss, 2),
            "realized_rr":  round(avg_win / abs(avg_loss), 2) if avg_loss else None,
            "exit_reasons": dict(d["exit_reasons"]),
        }
    return result


def build_weekly_aggregate(days: int = 7) -> dict:
    """
    Combined weekly view: funnel data summed from daily audits + real-trade
    risk math computed fresh from the trades table. This is the dict handed
    to both narrators (rule-based and AI) and saved to strategy_audits with
    audit_type='weekly'.
    """
    funnel, dates_included = _sum_daily_funnels(days)
    risk_math = _risk_math_from_real_trades(days)

    return {
        "week_label":       _iso_week_label(date.today()),
        "window_days":      days,
        "daily_audits_included": dates_included,
        "per_strategy_funnel":    funnel,
        "per_strategy_risk_math": risk_math,
    }

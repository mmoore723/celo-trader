"""
strategy_health/narrator.py — rule-based (free, no API call) plain-English
summary of a strategy health audit. Same template-driven approach as
strategy_audit_log.py, just summarizing a whole day instead of one bar.
"""

from __future__ import annotations

_STRAT_NAMES = {
    "V2_ORB_PULLBACK": "TSLA Opening-Range Pullback",
    "V2_SPY_TREND_CONT": "SPY Trend Continuation",
    "V2_SPY_AFTERNOON_FVG": "SPY Afternoon Fair Value Gap",
    "V2_TSLA_TWO_LEG_TREND_PULLBACK": "TSLA Two-Leg Trend Pullback",
}


def build_narrative(aggregate: dict) -> str:
    """
    aggregate shape (produced by runner.py):
      {
        "date": "YYYY-MM-DD",
        "tickers_scanned": [...],
        "per_strategy": {
            strategy_id: {
                "raw_signals": int, "router_survivors": int,
                "worked_raw": int, "worked_survivors": int,
                "actual_trades": int, "actual_wins": int, "actual_pnl": float,
            }, ...
        },
      }
    """
    lines: list[str] = []
    date = aggregate.get("date", "unknown date")
    tickers = aggregate.get("tickers_scanned", [])
    lines.append(f"Strategy health audit for {date} — {len(tickers)} ticker(s) scanned "
                 f"({', '.join(tickers) if tickers else 'none'}).")

    per_strategy = aggregate.get("per_strategy", {})
    if not per_strategy:
        lines.append("No raw signals found from any strategy today — quiet market or all "
                      "strategies sat out their session windows.")
        return "\n".join(lines)

    for strategy_id, row in sorted(per_strategy.items(), key=lambda kv: -kv[1].get("raw_signals", 0)):
        name = _STRAT_NAMES.get(strategy_id, strategy_id)
        raw  = row.get("raw_signals", 0)
        surv = row.get("router_survivors", 0)
        trades = row.get("actual_trades", 0)
        wins   = row.get("actual_wins", 0)
        pnl    = row.get("actual_pnl", 0.0)

        if raw == 0:
            lines.append(f"• {name} ({strategy_id}): no raw signals today.")
            continue

        surv_pct = surv / raw * 100 if raw else 0.0
        piece = f"• {name} ({strategy_id}): {raw} raw signal(s), {surv} survived the router ({surv_pct:.0f}%)"

        if trades:
            wr = wins / trades * 100 if trades else 0.0
            piece += f", {trades} actual trade(s), {wr:.0f}% win rate, ${pnl:+.2f} P&L."
        else:
            piece += ", 0 actual trades taken."

        # Flag the two patterns worth a human's attention, without diagnosing
        # a specific gate (that needs a targeted diag_*-style follow-up).
        if raw >= 5 and surv == 0:
            piece += (" ⚠️ Every raw signal was blocked before reaching the router — "
                      "worth checking which gate (ADX, confidence floor, session bias) "
                      "is filtering this strategy out entirely.")
        elif surv >= 3 and trades == 0:
            piece += (" ⚠️ Signals cleared the router but no trade was recorded — "
                      "check entry.py sizing/affordability rejections.")

        raw_wr  = row.get("worked_raw", 0) / raw * 100 if raw else 0.0
        surv_wr = row.get("worked_survivors", 0) / surv * 100 if surv else None
        piece += f" (60-min forward-move quality: raw {raw_wr:.0f}%"
        if surv_wr is not None:
            piece += f", survivors {surv_wr:.0f}%"
        piece += ")"

        lines.append(piece)

    return "\n".join(lines)


def build_weekly_narrative(aggregate: dict) -> str:
    """
    Rule-based (free) summary of a weekly rollup — see weekly.py for the
    aggregate shape (per_strategy_funnel + per_strategy_risk_math).
    """
    lines: list[str] = []
    week = aggregate.get("week_label", "this week")
    days_included = aggregate.get("daily_audits_included", [])
    lines.append(f"Weekly review for {week} — {len(days_included)} daily audit(s) rolled up.")

    risk_math = aggregate.get("per_strategy_risk_math", {})
    if not risk_math:
        lines.append("No closed trades in this window — nothing to evaluate yet.")
        return "\n".join(lines)

    for sid, d in sorted(risk_math.items(), key=lambda kv: -kv[1].get("n", 0)):
        name = _STRAT_NAMES.get(sid, sid)
        n = d.get("n", 0)
        if n == 0:
            continue
        piece = (
            f"• {name} ({sid}): {n} closed trade(s), {d.get('win_rate_pct', 0):.0f}% win rate, "
            f"${d.get('avg_pnl', 0):+.2f}/trade avg (${d.get('total_pnl', 0):+.2f} total)."
        )
        rr = d.get("realized_rr")
        if rr is not None:
            piece += f" Realized win:loss ${d.get('avg_win',0):.2f}:${abs(d.get('avg_loss',0)):.2f} ({rr}x)."
        if n < 10:
            piece += " Sample still thin (<10 trades) — read cautiously."
        lines.append(piece)

    return "\n".join(lines)

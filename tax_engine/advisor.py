"""
tax_engine/advisor.py — profit_advisor(): dynamic take-profit /
don't-take-profit recommendation based on account phase, milestone
progress, and the withdrawal safety gates.

Split out of the old single tax_engine.py (2026-08-01, file-size cleanup);
no logic changed, only relocated.
"""

from tax_engine.gates import evaluate_safety_gates

def profit_advisor(
    current_balance:     float,
    starting_capital:    float,
    total_realized_pnl:  float,
    monthly_pnl:         float,
    tax_rate_pct:        float,
    live_trades:         int   = 0,
    live_win_rate:       float = 0.0,
    profitable_months:   int   = 0,
    halt_events_30d:     int   = 0,
    total_swept_ytd:     float = 0.0,
    income_target:       float = 0.0,    # user's actual monthly income goal — 0 = calculate dynamically
) -> dict:
    """
    Dynamic take-profit / don't-take-profit recommendation.

    Hard-gate logic — ALL gates must pass before any withdrawal is suggested.
    Phases are still used for guidance text, but Phase 2 no longer allows
    any withdrawal. Withdrawals only open after every gate is green.

    The gates are intentionally strict because the cost of withdrawing too
    early (delayed compounding, smaller base, slower income mode) is far
    greater than the cost of waiting a few extra months.
    """
    profit_pct  = (current_balance - starting_capital) / max(starting_capital, 1) * 100
    net_monthly = monthly_pnl * (1 - tax_rate_pct / 100)
    phase = (
        1 if current_balance < 10_000 else
        2 if current_balance < 25_000 else
        3
    )

    # Proposed withdrawal for gate evaluation = 10% of net monthly (conservative)
    proposed = max(500, net_monthly * 0.10)

    safety = evaluate_safety_gates(
        current_balance    = current_balance,
        live_trades        = live_trades,
        live_win_rate      = live_win_rate,
        profitable_months  = profitable_months,
        net_monthly_pnl    = net_monthly,
        proposed_withdrawal= proposed,
        halt_events_30d    = halt_events_30d,
        total_profit_ytd   = total_realized_pnl,
        total_swept_ytd    = total_swept_ytd,
        combined_tax_rate  = tax_rate_pct / 100,
    )

    gates_passed = safety["gates_passed"]

    # ── Phase 1 and 2: hard no regardless of gates ────────────────────────────
    if phase in (1, 2):
        gap          = (25_000 if phase == 2 else 10_000) - current_balance
        monthly_rate = 0.15
        months_left  = max(1, min(60, int(gap / max(monthly_pnl, 1))))  # cap at 60 months
        # Compound cost: what $1k withdrawn today is worth at Phase 3
        cost_of_1k   = round(1_000 * ((1 + monthly_rate) ** months_left), 0)

        return {
            "phase":              phase,
            "recommendation":     "DO NOT TAKE PROFIT",
            "color":              "red",
            "gates_passed":       False,
            "safety":             safety,
            "reason": (
                f"You are in Phase {phase} — the compounding phase. "
                f"{'$25,000' if phase == 2 else '$10,000'} is the minimum before "
                f"withdrawal is even evaluated. You are ${gap:,.0f} away. "
                f"Every $1,000 withdrawn today would be worth "
                f"~${cost_of_1k:,.0f} by the time you reach Phase 3. "
                f"Withdrawal is locked until all 7 safety gates pass."
            ),
            "max_withdrawal":      0,
            "suggested_withdrawal":0,
            "phase_gap":           round(gap, 2),
            "months_to_next":      months_left,
            "net_monthly":         round(net_monthly, 2),
            "profit_pct":          round(profit_pct, 1),
            "cost_of_early_withdrawal": cost_of_1k,
        }

    # ── Phase 3 but safety gates not all passed ───────────────────────────────
    if not gates_passed:
        return {
            "phase":               3,
            "recommendation":      "DO NOT TAKE PROFIT",
            "color":               "red",
            "gates_passed":        False,
            "safety":              safety,
            "reason": (
                f"You have reached Phase 3 balance (${current_balance:,.0f}) "
                f"but {len(safety['blocking'])} safety gate(s) are still failing. "
                f"All 7 must be green before withdrawal is safe. "
                f"Blocking: {', '.join(safety['blocking'])}."
            ),
            "max_withdrawal":       0,
            "suggested_withdrawal": 0,
            "net_monthly":          round(net_monthly, 2),
            "profit_pct":           round(profit_pct, 1),
            "phase_gap":            0,
            "months_to_next":       0,
        }

    # ── Phase 3 + all gates passed ────────────────────────────────────────────
    # Max safe withdrawal: net monthly minus a 5% balance growth reserve
    # Hard ceiling: never take more than 70% of net monthly (leaves 30% compounding)
    growth_reserve   = current_balance * 0.05
    max_withdrawal   = max(0, round(net_monthly - growth_reserve, 2))
    max_withdrawal   = min(max_withdrawal, net_monthly * 0.70)
    # No hardcoded cap — suggestion is the full safe withdrawal amount.
    # The dashboard passes the user's actual income target and we display
    # both their target AND the mathematical maximum.
    suggested        = max_withdrawal

    if net_monthly <= 0:
        return {
            "phase": 3, "recommendation": "DO NOT TAKE PROFIT",
            "color": "red", "gates_passed": True, "safety": safety,
            "reason": "Net P&L this month is flat or negative. Hold all capital.",
            "max_withdrawal": 0, "suggested_withdrawal": 0,
            "net_monthly": round(net_monthly, 2), "profit_pct": round(profit_pct, 1),
            "phase_gap": 0, "months_to_next": 0,
        }

    if max_withdrawal < 500:
        rec    = "DO NOT TAKE PROFIT"
        color  = "red"
        reason = (
            f"Net gains after tax (${net_monthly:,.0f}) are not yet large enough "
            f"to safely withdraw after keeping the 5% growth reserve. "
            f"Let the account grow another month."
        )
    elif net_monthly >= max_withdrawal * 2:
        rec    = "TAKE PROFIT"
        color  = "green"
        reason = (
            f"✅ All 7 safety gates passed. Strong month — net ${net_monthly:,.0f}. "
            f"Safe to withdraw up to ${max_withdrawal:,.2f}. "
            f"This preserves ${growth_reserve:,.0f} growth reserve in the account."
        )
    else:
        rec    = "TAKE PROFIT — CAUTIOUSLY"
        color  = "yellow"
        reason = (
            f"✅ All gates passed. Moderate month. Suggested: ${suggested:,.2f}. "
            f"Do not exceed ${max_withdrawal:,.2f} — above that, growth stalls."
        )

    return {
        "phase":               3,
        "recommendation":      rec,
        "color":               color,
        "gates_passed":        True,
        "safety":              safety,
        "reason":              reason,
        "max_withdrawal":      max_withdrawal,
        "suggested_withdrawal":suggested,
        "income_target":       income_target,
        "net_monthly":         round(net_monthly, 2),
        "growth_reserve":      round(growth_reserve, 2),
        "profit_pct":          round(profit_pct, 1),
        "phase_gap":           0,
        "months_to_next":      0,
    }



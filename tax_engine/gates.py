"""
tax_engine/gates.py — WITHDRAWAL_GATES thresholds and
evaluate_safety_gates(): the hard-gate check that must all pass before any
withdrawal is permitted.

Split out of the old single tax_engine.py (2026-08-01, file-size cleanup);
no logic changed, only relocated.
"""

# ── Profit advisor ─────────────────────────────────────────────────────────────

# ── Safety gate constants ─────────────────────────────────────────────────────
# ALL of these must be true before ANY withdrawal is permitted.
# These are not suggestions — they are hard gates.

WITHDRAWAL_GATES = {
    # Minimum account balance before the question of withdrawal even opens
    "min_balance":              25_000.0,

    # Minimum number of LIVE (non-paper) closed trades on record
    # 8 trades is roughly 2 weeks of normal signal activity.
    # Paper trades don't count — you need real-money proof.
    "min_live_trades":          8,

    # Minimum win rate across those live trades
    "min_live_win_rate":        0.60,

    # Minimum consecutive profitable calendar months (live trading)
    # One good month could be luck. Two in a row starts to be signal.
    "min_profitable_months":    2,

    # The net monthly profit must be at least this multiple of the withdrawal
    # 3x = you make $3 for every $1 you take out. Below that, the withdrawal
    # meaningfully impacts compounding velocity.
    "min_profit_coverage":      3.0,

    # Max times daily loss limit was hit in the last 30 days.
    # Hitting the halt twice in a month means the strategy is struggling.
    "max_halt_events_30d":      2,

    # Tax reserve must be funded — cannot withdraw if tax account is short.
    # We check: total_swept >= total_profit * combined_rate * 0.95
    # (95% threshold to allow small rounding differences)
    "tax_reserve_coverage":     0.95,
}


def evaluate_safety_gates(
    current_balance:      float,
    live_trades:          int,
    live_win_rate:        float,
    profitable_months:    int,
    net_monthly_pnl:      float,
    proposed_withdrawal:  float,
    halt_events_30d:      int,
    total_profit_ytd:     float,
    total_swept_ytd:      float,
    combined_tax_rate:    float,
) -> dict:
    """
    Check every safety gate. Returns a dict with:
      - gates_passed: bool (ALL must be True)
      - gates: list of individual gate results
      - blocking_reason: human-readable explanation of what's failing
    """
    gates = []

    # Gate 1: Balance threshold
    gates.append({
        "name":   "Account Balance ≥ $25,000",
        "passed": current_balance >= WITHDRAWAL_GATES["min_balance"],
        "actual": f"${current_balance:,.0f}",
        "required": f"${WITHDRAWAL_GATES['min_balance']:,.0f}",
        "why": "Below $25k you are still in the compounding phase. "
               "Withdrawing now delays income mode by months.",
    })

    # Gate 2: Minimum live trades
    gates.append({
        "name":   "≥ 8 Live Trades on Record",
        "passed": live_trades >= WITHDRAWAL_GATES["min_live_trades"],
        "actual": f"{live_trades} trades",
        "required": f"{WITHDRAWAL_GATES['min_live_trades']} trades",
        "why": "You need enough real-money trades to know the win rate is real, "
               "not a lucky streak. Paper trades do not count.",
    })

    # Gate 3: Win rate
    gates.append({
        "name":   "Live Win Rate ≥ 60%",
        "passed": live_win_rate >= WITHDRAWAL_GATES["min_live_win_rate"] or live_trades == 0,
        "actual": f"{live_win_rate*100:.1f}%" if live_trades > 0 else "No live trades yet",
        "required": f"{WITHDRAWAL_GATES['min_live_win_rate']*100:.0f}%",
        "why": "A sub-60% win rate with this R:R means you are losing money "
               "on a risk-adjusted basis. Do not withdraw from a losing strategy.",
    })

    # Gate 4: Consecutive profitable months
    gates.append({
        "name":   "≥ 2 Consecutive Profitable Months",
        "passed": profitable_months >= WITHDRAWAL_GATES["min_profitable_months"],
        "actual": f"{profitable_months} month(s)",
        "required": f"{WITHDRAWAL_GATES['min_profitable_months']} months",
        "why": "One good month is noise. Two in a row in live trading "
               "is the minimum signal that the strategy is working.",
    })

    # Gate 5: Profit coverage ratio
    coverage = net_monthly_pnl / max(proposed_withdrawal, 1)
    gates.append({
        "name":   "Monthly Profit ≥ 3× Withdrawal",
        "passed": coverage >= WITHDRAWAL_GATES["min_profit_coverage"],
        "actual": f"{coverage:.1f}× coverage",
        "required": f"{WITHDRAWAL_GATES['min_profit_coverage']}× coverage",
        "why": "If you make $3 for every $1 withdrawn, the account still grows "
               "strongly. Below 3× the withdrawal materially slows compounding.",
    })

    # Gate 6: Halt events
    gates.append({
        "name":   "Fewer Than 2 Daily Halts (Last 30 Days)",
        "passed": halt_events_30d <= WITHDRAWAL_GATES["max_halt_events_30d"],
        "actual": f"{halt_events_30d} halt(s)",
        "required": f"≤ {WITHDRAWAL_GATES['max_halt_events_30d']} halts",
        "why": "Hitting the daily loss limit repeatedly signals the strategy "
               "is struggling. Withdrawing while struggling accelerates account damage.",
    })

    # Gate 7: Tax reserve funded
    required_reserve = total_profit_ytd * combined_tax_rate * WITHDRAWAL_GATES["tax_reserve_coverage"]
    tax_ok = total_swept_ytd >= required_reserve or total_profit_ytd == 0
    gates.append({
        "name":   "Tax Reserve Fully Funded",
        "passed": tax_ok,
        "actual": f"${total_swept_ytd:,.2f} reserved",
        "required": f"${required_reserve:,.2f} needed",
        "why": "You cannot withdraw money you owe the IRS. The tax reserve "
               "must be fully funded before any discretionary withdrawal.",
    })

    all_passed = all(g["passed"] for g in gates)
    blocking   = [g["name"] for g in gates if not g["passed"]]

    return {
        "gates_passed":    all_passed,
        "gates":           gates,
        "blocking":        blocking,
        "blocking_reason": (
            "All safety gates passed." if all_passed else
            "Withdrawal blocked by: " + ", ".join(blocking)
        ),
    }



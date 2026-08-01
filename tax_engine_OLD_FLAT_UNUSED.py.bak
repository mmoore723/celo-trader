"""
tax_engine.py — Tax calculation, auto-sweep, and profit-taking advisor.

Three jobs:
──────────
1. TAX CALCULATOR
   Given salary, filing status, and state, compute the EXACT marginal rate
   that applies to trading income. This is not a flat 30% guess — it uses
   the actual 2024 federal bracket stack plus your state rate.
   Why this matters: a $60k salaried person in Texas pays ~22% on trading
   gains. The same person in California pays ~35%. Withholding the wrong
   amount is a silent mistake that compounds all year.

2. AUTO-SWEEP
   Every time a trade closes in profit, tax_engine.record_sweep() is called
   automatically from trading_logic.py. It calculates the exact reserve
   amount, stores it in the database, and updates a running "set aside" total.
   The money doesn't actually move (we can't touch your bank account) — but
   the dashboard shows a clear "DO NOT SPEND THIS" reserve balance that
   tracks every dollar you owe.

3. PROFIT ADVISOR
   Dynamic take-profit / don't-take-profit recommendation based on:
   - Current account balance vs starting capital
   - Phase of growth (compounding vs income mode)
   - Whether taking profit now would stall reaching the next milestone
   - A hard cap suggestion: maximum you should ever withdraw in one month
     without meaningfully slowing compounding.
"""

import json
import logging
from datetime import datetime, date
from pathlib import Path
from typing import Optional

from config import DB_PATH, get_settings, STARTING_CAPITAL

logger = logging.getLogger("celo_trader.tax_engine")

# ── Paths ─────────────────────────────────────────────────────────────────────
TAX_PROFILE_PATH = Path(__file__).resolve().parent / "tax_profile.json"
TAX_SWEEP_PATH   = Path(__file__).resolve().parent / "tax_sweep.json"


# ── 2024 Federal Tax Brackets ─────────────────────────────────────────────────
# Each tuple: (income_ceiling, marginal_rate)
# Trading income (short-term options) is taxed as ordinary income.

FEDERAL_BRACKETS = {
    "single": [
        (11_600,        0.10),
        (47_150,        0.12),
        (100_525,       0.22),
        (191_950,       0.24),
        (243_725,       0.32),
        (609_350,       0.35),
        (float("inf"), 0.37),
    ],
    "married_jointly": [
        (23_200,        0.10),
        (94_300,        0.12),
        (201_050,       0.22),
        (383_900,       0.24),
        (487_450,       0.32),
        (731_200,       0.35),
        (float("inf"), 0.37),
    ],
    "married_separately": [
        (11_600,        0.10),
        (47_150,        0.12),
        (100_525,       0.22),
        (191_950,       0.24),
        (243_725,       0.32),
        (365_600,       0.35),
        (float("inf"), 0.37),
    ],
    "head_of_household": [
        (16_550,        0.10),
        (63_100,        0.12),
        (100_500,       0.22),
        (191_950,       0.24),
        (243_700,       0.32),
        (609_350,       0.35),
        (float("inf"), 0.37),
    ],
}

# ── State income tax rates (top marginal / effective flat rate) ───────────────
# Source: Tax Foundation 2024. Using top marginal rate as conservative estimate.
# Zero = no state income tax on ordinary income.
STATE_RATES = {
    "AL": 0.050, "AK": 0.000, "AZ": 0.025, "AR": 0.044, "CA": 0.133,
    "CO": 0.044, "CT": 0.069, "DE": 0.066, "FL": 0.000, "GA": 0.055,
    "HI": 0.110, "ID": 0.058, "IL": 0.050, "IN": 0.031, "IA": 0.060,
    "KS": 0.057, "KY": 0.045, "LA": 0.042, "ME": 0.072, "MD": 0.058,
    "MA": 0.050, "MI": 0.043, "MN": 0.099, "MS": 0.050, "MO": 0.054,
    "MT": 0.069, "NE": 0.066, "NV": 0.000, "NH": 0.000, "NJ": 0.108,
    "NM": 0.059, "NY": 0.109, "NC": 0.053, "ND": 0.029, "OH": 0.040,
    "OK": 0.050, "OR": 0.099, "PA": 0.031, "RI": 0.060, "SC": 0.064,
    "SD": 0.000, "TN": 0.000, "TX": 0.000, "UT": 0.047, "VT": 0.088,
    "VA": 0.058, "WA": 0.000, "WV": 0.065, "WI": 0.077, "WY": 0.000,
    "DC": 0.108,
}

STATE_NAMES = {
    "AL":"Alabama","AK":"Alaska","AZ":"Arizona","AR":"Arkansas","CA":"California",
    "CO":"Colorado","CT":"Connecticut","DE":"Delaware","FL":"Florida","GA":"Georgia",
    "HI":"Hawaii","ID":"Idaho","IL":"Illinois","IN":"Indiana","IA":"Iowa",
    "KS":"Kansas","KY":"Kentucky","LA":"Louisiana","ME":"Maine","MD":"Maryland",
    "MA":"Massachusetts","MI":"Michigan","MN":"Minnesota","MS":"Mississippi","MO":"Missouri",
    "MT":"Montana","NE":"Nebraska","NV":"Nevada","NH":"New Hampshire","NJ":"New Jersey",
    "NM":"New Mexico","NY":"New York","NC":"North Carolina","ND":"North Dakota","OH":"Ohio",
    "OK":"Oklahoma","OR":"Oregon","PA":"Pennsylvania","RI":"Rhode Island","SC":"South Carolina",
    "SD":"South Dakota","TN":"Tennessee","TX":"Texas","UT":"Utah","VT":"Vermont",
    "VA":"Virginia","WA":"Washington","WV":"West Virginia","WI":"Wisconsin","WY":"Wyoming",
    "DC":"Washington DC",
}

FILING_LABELS = {
    "single":             "Single",
    "married_jointly":    "Married Filing Jointly",
    "married_separately": "Married Filing Separately",
    "head_of_household":  "Head of Household",
}


# ── Tax profile persistence ───────────────────────────────────────────────────

def save_tax_profile(profile: dict) -> None:
    """Save user's salary, filing status, state to disk."""
    with open(TAX_PROFILE_PATH, "w") as f:
        json.dump(profile, f, indent=2)


def load_tax_profile() -> dict:
    """Load tax profile. Returns sensible defaults if not yet configured."""
    defaults = {
        "salary":         0,
        "filing_status":  "single",
        "state":          "TX",
        "tts_elected":    False,   # Trader Tax Status — consult a CPA
        "ytd_trading_pnl": 0.0,   # year-to-date realized gains (manually updated)
    }
    if TAX_PROFILE_PATH.exists():
        try:
            with open(TAX_PROFILE_PATH) as f:
                saved = json.load(f)
            defaults.update(saved)
        except (json.JSONDecodeError, OSError):
            pass
    return defaults


# ── Core tax calculation ───────────────────────────────────────────────────────

def compute_marginal_rate(
    salary: float,
    filing_status: str,
    state: str,
    ytd_trading_pnl: float = 0.0,
) -> dict:
    """
    Compute the exact marginal tax rate that applies to the NEXT dollar of
    trading income, given existing salary and YTD trading gains.

    Why marginal and not effective?
    Your salary already pushes you into a bracket. Trading income stacks
    on top. We need to know which bracket that next dollar lands in,
    not the average rate across all income — that would underestimate
    the reserve needed.

    Returns a dict with federal_rate, state_rate, combined_rate, bracket_info.
    """
    filing = filing_status if filing_status in FEDERAL_BRACKETS else "single"
    brackets = FEDERAL_BRACKETS[filing]

    # Income already earned before trading gains
    base_income = salary + ytd_trading_pnl

    # Find which federal bracket the next trading dollar lands in
    federal_marginal = 0.37   # default to top
    bracket_label    = "37%"
    for ceiling, rate in brackets:
        if base_income < ceiling:
            federal_marginal = rate
            bracket_label    = f"{int(rate*100)}%"
            break

    state_rate   = STATE_RATES.get(state.upper(), 0.0)
    combined     = federal_marginal + state_rate

    # Self-employment / SE tax note: options trading income is NOT subject
    # to SE tax (15.3%) because it's investment income, not earned income.
    # TTS election changes some deductions but not this core rate.

    return {
        "federal_rate":    round(federal_marginal, 4),
        "state_rate":      round(state_rate, 4),
        "combined_rate":   round(combined, 4),
        "combined_pct":    round(combined * 100, 1),
        "federal_bracket": bracket_label,
        "state_name":      STATE_NAMES.get(state.upper(), state),
        "no_state_tax":    state_rate == 0.0,
        "filing_label":    FILING_LABELS.get(filing, filing),
        "base_income":     base_income,
    }


def reserve_for_trade(gross_pnl: float, tax_info: dict) -> float:
    """
    Given a realized profit and tax info dict, return the dollar amount
    to move to the tax reserve account.
    Add a 2% cushion on top of the calculated rate to account for
    any state underpayment penalties or bracket creep mid-year.
    """
    if gross_pnl <= 0:
        return 0.0
    cushion_rate = tax_info["combined_rate"] + 0.02
    return round(gross_pnl * min(cushion_rate, 0.45), 2)   # cap at 45%


# ── Sweep ledger ──────────────────────────────────────────────────────────────

def load_sweep_ledger() -> dict:
    """Load the running tax sweep totals."""
    defaults = {
        "total_swept":    0.0,
        "total_profit":   0.0,
        "effective_rate": 0.0,
        "entries":        [],
        "ytd_year":       date.today().year,
    }
    if TAX_SWEEP_PATH.exists():
        try:
            with open(TAX_SWEEP_PATH) as f:
                saved = json.load(f)
            # Reset if new calendar year
            if saved.get("ytd_year") != date.today().year:
                saved["total_swept"]    = 0.0
                saved["total_profit"]   = 0.0
                saved["entries"]        = []
                saved["ytd_year"]       = date.today().year
            defaults.update(saved)
        except (json.JSONDecodeError, OSError):
            pass
    return defaults


def record_sweep(gross_pnl: float, trade_id: int) -> float:
    """
    Called automatically when a profitable trade closes.
    Calculates reserve, logs it to the sweep ledger, returns the reserve amount.
    """
    if gross_pnl <= 0:
        return 0.0

    profile  = load_tax_profile()
    ledger   = load_sweep_ledger()
    tax_info = compute_marginal_rate(
        profile["salary"],
        profile["filing_status"],
        profile["state"],
        ytd_trading_pnl=ledger["total_profit"],
    )

    reserve = reserve_for_trade(gross_pnl, tax_info)

    ledger["total_swept"]    = round(ledger["total_swept"] + reserve, 2)
    ledger["total_profit"]   = round(ledger["total_profit"] + gross_pnl, 2)
    ledger["effective_rate"] = round(
        ledger["total_swept"] / ledger["total_profit"] * 100, 1
    ) if ledger["total_profit"] > 0 else 0.0
    ledger["entries"].append({
        "ts":       datetime.utcnow().isoformat(),
        "trade_id": trade_id,
        "profit":   gross_pnl,
        "reserved": reserve,
        "rate_pct": tax_info["combined_pct"],
    })

    try:
        with open(TAX_SWEEP_PATH, "w") as f:
            json.dump(ledger, f, indent=2)
    except OSError as e:
        logger.error("Failed to write sweep ledger: %s", e)

    logger.info(
        "Tax sweep: trade_id=%d profit=$%.2f reserved=$%.2f (%.1f%%)",
        trade_id, gross_pnl, reserve, tax_info["combined_pct"],
    )
    return reserve


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


# ── Quarterly estimated tax reminder ─────────────────────────────────────────

QUARTERLY_DEADLINES = [
    (4, 15,  "Q1 estimated tax due (Jan–Mar income)"),
    (6, 17,  "Q2 estimated tax due (Apr–May income)"),
    (9, 16,  "Q3 estimated tax due (Jun–Aug income)"),
    (1, 15,  "Q4 estimated tax due (Sep–Dec income)"),  # next year Jan 15
]

def next_tax_deadline() -> Optional[dict]:
    """Return the next upcoming quarterly estimated tax deadline."""
    today = date.today()
    for month, day, label in QUARTERLY_DEADLINES:
        year = today.year if month >= today.month else today.year + 1
        deadline = date(year, month, day)
        if deadline >= today:
            days_away = (deadline - today).days
            return {
                "date":      deadline.isoformat(),
                "label":     label,
                "days_away": days_away,
                "urgent":    days_away <= 30,
            }
    return None
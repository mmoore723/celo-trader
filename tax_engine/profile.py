"""
tax_engine/profile.py — Tax profile persistence (save/load) and the
core marginal-rate calculation (federal bracket stack + state rate).

Split out of the old single tax_engine.py (2026-08-01, file-size cleanup);
no logic changed, only relocated.
"""

import json
from datetime import date

from tax_engine.constants import (
    FEDERAL_BRACKETS, STATE_RATES, STATE_NAMES, FILING_LABELS, TAX_PROFILE_PATH,
)

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



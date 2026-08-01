"""
tax_engine/ — Tax calculation, auto-sweep, and profit-taking advisor.

Split from the old single tax_engine.py into themed modules (2026-08-01,
file-size cleanup) — no logic changed anywhere, only relocated. This
__init__.py re-exports every public name the old flat module did (only
record_sweep is currently used outside this module, by trading code, but
every name is re-exported for completeness/future use):

  constants.py — federal brackets, state rates/names, filing labels, paths
  profile.py    — save/load_tax_profile, compute_marginal_rate, reserve_for_trade
  sweep.py       — load_sweep_ledger, record_sweep
  gates.py        — WITHDRAWAL_GATES, evaluate_safety_gates
  advisor.py        — profit_advisor
  deadline.py         — next_tax_deadline

Three jobs:
──────────
1. TAX CALCULATOR — exact marginal rate from 2024 federal brackets + state rate.
2. AUTO-SWEEP — every profitable trade close reserves the exact tax amount.
3. PROFIT ADVISOR — dynamic take-profit recommendation + withdrawal safety gates.
"""

from tax_engine.constants import (
    TAX_PROFILE_PATH, TAX_SWEEP_PATH,
    FEDERAL_BRACKETS, STATE_RATES, STATE_NAMES, FILING_LABELS,
)
from tax_engine.profile import save_tax_profile, load_tax_profile, compute_marginal_rate, reserve_for_trade
from tax_engine.sweep import load_sweep_ledger, record_sweep
from tax_engine.gates import WITHDRAWAL_GATES, evaluate_safety_gates
from tax_engine.advisor import profit_advisor
from tax_engine.deadline import next_tax_deadline

__all__ = [
    "TAX_PROFILE_PATH", "TAX_SWEEP_PATH",
    "FEDERAL_BRACKETS", "STATE_RATES", "STATE_NAMES", "FILING_LABELS",
    "save_tax_profile", "load_tax_profile", "compute_marginal_rate", "reserve_for_trade",
    "load_sweep_ledger", "record_sweep",
    "WITHDRAWAL_GATES", "evaluate_safety_gates",
    "profit_advisor",
    "next_tax_deadline",
]

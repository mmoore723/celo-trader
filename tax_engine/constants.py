"""
tax_engine/constants.py — Federal tax brackets, state rates/names, filing
status labels, and the two on-disk profile/sweep file paths.

Split out of the old single tax_engine.py (2026-08-01, file-size cleanup);
no logic changed, only relocated.
"""

import json
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
# FIX 2026-08-01 (package-split path bug): the old flat tax_engine.py lived
# directly in the project root, so Path(__file__).resolve().parent pointed at
# the root. This file now lives one level deeper at tax_engine/constants.py,
# so the same expression would resolve to tax_engine/ instead — silently
# writing a NEW tax_sweep.json/tax_profile.json inside the package directory
# instead of updating the real ones. Caught by a real smoke test that called
# record_sweep() and found no new entry in the root-level tax_sweep.json.
# The extra .parent accounts for the added nesting depth.
TAX_PROFILE_PATH = Path(__file__).resolve().parent.parent / "tax_profile.json"
TAX_SWEEP_PATH   = Path(__file__).resolve().parent.parent / "tax_sweep.json"


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



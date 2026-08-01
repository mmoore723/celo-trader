"""
signal_journal/constants.py — REASON_CODES reference map.

Split out of the old single signal_journal.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""
from __future__ import annotations

# Reason codes used across router_gates.py and trading/entry.py. Kept as a
# single reference list here so both call sites (and the frontend filter
# dropdown, via the /api/signals/journal/reasons endpoint) stay in sync.
REASON_CODES = {
    "confidence_floor":      "Confidence below the entry floor",
    "grade_filter":          "Premarket grade below the minimum",
    "conflict_veto":         "Top two signals disagree — market ambiguous",
    "volume_roc_veto":       "Buying/selling pressure already fading",
    "directional_consensus": "3/3 indicators agree the other direction",
    "regime_gate":           "Market regime blocks this direction",
    "macro_vwap_veto":       "Conflicts with SPY/QQQ or ticker's own VWAP posture",
    "budget":                "Cheapest contract costs more than the spend cap",
    "illiquid_contract":     "An affordable contract existed but failed spread/OI filters",
    "no_option_data":        "No usable options chain returned",
    "no_liquid_contracts":   "No contract met spread/open-interest filters",
    "zero_contracts":        "Risk budget too small to size even 1 contract",
    "spread_too_wide":       "Bid-ask spread wider than the spread gate",
    "rr_too_low":            "Reward:risk below the 1.6x minimum",
    "ai_decision_veto":      "AI decision-support layer vetoed or zeroed the size",
}

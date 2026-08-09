"""Read-only, human-friendly summary of the completed paid TSLA study.

The source reports are intentionally kept outside version control because they
contain a large paid data archive.  These reviewed figures preserve the result
inside the product without exposing that archive or allowing an API response to
silently change trading configuration.
"""
from __future__ import annotations


def v2_orb_tsla_summary() -> dict:
    """Return evidence, never a trading recommendation or an order command."""
    return {
        "study_id": "paid_tsla_v2_orb_2025_08_to_2026_08",
        "label": "TSLA Opening-Range Pullback — paid historical study",
        "status": "paper_validation_next",
        "ticker": "TSLA",
        "strategy_id": "V2_ORB_PULLBACK",
        "data_scope": "251 TSLA market sessions from the purchased OPRA archive",
        "execution_model": "Each result buys at an observed option ask and exits the same contract at an observed option bid; it never uses a synthetic option price or midpoint.",
        "baseline": {
            "label": "Unchanged V2 entry + 90-minute exit",
            "measured_signals": 39,
            "win_rate_pct": 61.54,
            "average_return_pct": 6.3776,
        },
        "unseen_holdout": {
            "label": "Later dates never used to choose the setting",
            "measured_signals": 12,
            "win_rate_pct": 75.0,
            "average_return_pct": 4.4572,
        },
        "walkforward": {
            "label": "Month-by-month: choose only from earlier results",
            "baseline": {"measured_signals": 26, "average_return_pct": 6.5852},
            "best_past_variant": {"measured_signals": 25, "average_return_pct": 2.1722},
        },
        "what_changed": "Nothing. VWAP and EMA exits, plus five predeclared entry variations, did not beat the unchanged baseline fairly enough to justify a replacement.",
        "next_step": "Run only the unchanged baseline in paper mode and compare its prospective broker fills with this historical evidence.",
        "caveat": "Historical results are not a promise of future profit. This study is small, uses fixed 90-minute markouts, and does not yet include prospective broker-fill latency or commissions.",
    }

"""Run every deployable application test without private research-workspace tests.

The repository intentionally deploys the application but not local paid-data
research scripts.  Tests listed below import those non-deployable scripts and
are run in the research workspace instead.  Keeping the exclusion explicit
means a new broken application test cannot be silently skipped.
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest


RESEARCH_WORKSPACE_ONLY = {
    "test_cross_ticker_afternoon_compression",
    "test_ema_risk_depth_screen",
    "test_impulse_anchored_vwap_paid_exits",
    "test_initial_balance_midpoint_rotation",
    "test_initial_balance_retest",
    "test_market_relative_snapback",
    "test_market_relative_snapback_tuning",
    "test_nr7_inside_day_breakout",
    "test_paid_afternoon_reversal_momentum",
    "test_paid_candidate_robustness",
    "test_paid_chronological_stability",
    "test_paid_compression_walk_forward",
    "test_paid_indicator_filter_value",
    "test_paid_markout_context",
    "test_paid_markouts_holdout",
    "test_paid_option_eligibility_diagnostic",
    "test_paid_option_eligibility_timing_summary",
    "test_paid_price_action_three_period",
    "test_paid_range_sweep_transfer_diagnostic",
    "test_paid_setup_ranker",
    "test_paid_signal_thesis_coordination",
    "test_paid_spy_afternoon_compression_confirmation",
    "test_paid_spy_afternoon_compression_confirmation_selection",
    "test_paid_spy_afternoon_compression_context",
    "test_paid_spy_afternoon_compression_exits",
    "test_paid_spy_afternoon_fvg_entry_timing",
    "test_paid_spy_afternoon_reversal_exit_selection",
    "test_paid_spy_afternoon_reversal_exits",
    "test_paid_spy_noise_failure_validation",
    "test_paid_strategy_ranker",
    "test_paid_three_period_contexts",
    "test_paid_tsla_orb_retouch_contexts",
    "test_paid_tsla_range_sweep_transfer",
    "test_research_v2",
    "test_rsi_macd_vwap_momentum",
    "test_spy_closing_drive_contexts",
    "test_spy_first_last_half_hour",
    "test_spy_strategy_portfolio",
    "test_suggested_strategy_changes",
    "test_time_of_day_periodicity",
    "test_tsla_noise_momentum_account",
    "test_two_leg_tuning",
}


def main() -> int:
    test_dir = Path(__file__).resolve().parent
    repo_root = test_dir.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    modules = [
        f"tests.{path.stem}"
        for path in sorted(test_dir.glob("test_*.py"))
        if path.stem not in RESEARCH_WORKSPACE_ONLY
    ]
    suite = unittest.defaultTestLoader.loadTestsFromNames(modules)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())

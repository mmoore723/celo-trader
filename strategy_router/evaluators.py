"""
strategy_router/evaluators.py — Active strategy evaluator table.

Split out of the old single strategy_router.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.

This is the production execution allowlist. Research strategies live under
``research/`` and must not be added here until their paid-quote evidence is
reviewed and they are promoted in ``config.strategy_catalog``.

Legacy evaluators intentionally remain importable for historical reports, but
they are not imported or evaluated by the production router. Keeping the
allowlist narrow prevents a stale per-user toggle from reviving an old rule.
"""

from strategies import (
    orb_pullback_v2, spy_trend_continuation_v2, spy_afternoon_fvg_v2,
)

# ── Active evaluator table (single source of truth) ───────────────────────────
ACTIVE_STRATEGIES = [
    ("V2_ORB_PULLBACK", orb_pullback_v2.evaluate),
    ("V2_SPY_TREND_CONT", spy_trend_continuation_v2.evaluate),
    ("V2_SPY_AFTERNOON_FVG", spy_afternoon_fvg_v2.evaluate),
]

"""
strategy_router/evaluators.py — Active strategy evaluator table.

Split out of the old single strategy_router.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.

This is the production execution allowlist. Research strategies live under
``research/`` and must not be added here until their paid-quote evidence is
reviewed and they are promoted in ``config.strategy_catalog``.

Legacy and rejected evaluators have been removed from the production tree.
Research candidates live only under ``research/`` until promotion.
"""

from config.strategy_catalog import strategy_ids_for_source
from strategies import spy_trend_continuation_v2, spy_afternoon_fvg_v2, spy_failed_range_recovery_v2
from strategies.context_strategy_observers import ACTIVE_OBSERVERS

# ── Active evaluator table (single source of truth) ───────────────────────────
ACTIVE_STRATEGIES = [
    ("V2_SPY_TREND_CONT", spy_trend_continuation_v2.evaluate),
    ("V2_SPY_AFTERNOON_FVG", spy_afternoon_fvg_v2.evaluate),
    ("V2_FAILED_OR_BREAK_VWAP_REVERSION", spy_failed_range_recovery_v2.evaluate),
    *ACTIVE_OBSERVERS,
]

_implemented_ids = {strategy_id for strategy_id, _evaluate in ACTIVE_STRATEGIES}
_registered_ids = strategy_ids_for_source("bar_close")
if _implemented_ids != _registered_ids:
    raise RuntimeError(
        "Reviewed bar-close strategy registry mismatch: "
        f"implemented={sorted(_implemented_ids)} registered={sorted(_registered_ids)}"
    )

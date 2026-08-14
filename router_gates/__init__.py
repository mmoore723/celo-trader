"""
router_gates/__init__.py — Sequential signal-quality gates applied by
strategy_router (via `import router_gates as _gates`).

Split out of the old single router_gates.py (2026-08-01, file-size
cleanup); no logic changed, only relocated. Re-exports every gate function
as a package-level attribute so strategy_router.py's `_gates.apply_*` /
`_gates.check_*` call sites keep working unchanged.

Pipeline order (must match strategy_router.route_signals()):
  1. apply_session_bias_penalty   (confidence tax)
  3. apply_vwap_weight            (confidence tax)
  4. apply_confluence_bonus       (confidence boost)
  5. apply_mtf_confirmation       (confidence tax/boost — OFF by default, live-only)
  5b. apply_grade_filter          (filter — OFF by default, mirrors dashboard grade)
  6. apply_large_move_gate        (confidence cap)
  7. apply_directional_consensus  (filter or penalty)
  8. apply_confidence_floor       (filter)
  9. check_conflict_veto          (early return if True)
  10. check_volume_roc_veto       (early return if True)
"""

from router_gates.helpers import _journal_dropped
from router_gates.session_vwap import apply_session_bias_penalty, apply_vwap_weight
from router_gates.confluence_mtf import apply_confluence_bonus, apply_mtf_confirmation
from router_gates.grade_filter import apply_grade_filter
from router_gates.move_consensus import apply_large_move_gate, apply_directional_consensus
from router_gates.confidence_floor import apply_confidence_floor
from router_gates.vetoes import check_conflict_veto, check_volume_roc_veto

__all__ = [
    "_journal_dropped",
    "apply_session_bias_penalty", "apply_vwap_weight",
    "apply_confluence_bonus", "apply_mtf_confirmation",
    "apply_grade_filter",
    "apply_large_move_gate", "apply_directional_consensus",
    "apply_confidence_floor",
    "check_conflict_veto", "check_volume_roc_veto",
]

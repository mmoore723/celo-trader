"""
strategies/trend_cont/constants.py — strategy ID and tunables.

Split out of the old single strategies/trend_cont.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.

IMPORTANT: archived diagnostic scripts (scripts/diagnostics/archive/
ab_test_v2_fixes.py, ab_test_trend_cont_maxbars.py,
scripts/ab_tests/ab_test_structural_stop_mode.py) monkey-patch
_MAX_BARS, _MIN_DEPTH_PCT, and STRUCT_STOP_MODE directly on the PACKAGE
object at runtime, e.g. `trend_cont._MAX_BARS = 10`. For that mutation to
actually take effect, evaluate.py must read these three via a fresh dotted
lookup on the live package object at call time, NOT via a
`from constants import X` binding captured once at import time (which
would silently go stale and never see the monkey-patch) — same pattern as
strategies/vwap_pb.py and strategy_router.py earlier in this refactor.
STRATEGY_ID and _RVOL_MIN are not monkey-patched anywhere (confirmed via
grep), so they're read normally.
"""

STRATEGY_ID = "TREND_CONT"

_RVOL_MIN   = 1.2
_MAX_BARS   = 6    # tightened from 10 (2026-07-21, pending A/B) — see package docstring
_MIN_DEPTH_PCT = 0.70   # min lh_depth_pct/hl_rise_pct, in % (2026-07-21, pending A/B)

# ── Structural stop reference (2026-07-22, A/B tested — see result below) ─────
# Which level to hand off as entry_bar_high/low for the exit engine's
# structural stop. ab_test_structural_stop_mode.py ran all 4 (SPY/QQQ, 2mo,
# post RR/RVOL bug fixes): prior_swing won clearly, beating even "none"
# (ATR-only). pivot and entry_bar (tighter) were both worse. Shipped as
# default 2026-07-22.
#   "prior_swing" — the swing BEFORE the LH/HL (wider) — DEFAULT, A/B winner
#   "pivot"       — the LH/HL price this signal re-enters on (was default)
#   "entry_bar"   — this bar's own high/low (tightest, mirrors INST_ORB) — worst
#   "none"        — no structural stop; ATR fallback only (pre-2026-07-21 behavior)
STRUCT_STOP_MODE = "prior_swing"

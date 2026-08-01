"""
strategies/aft_rev/constants.py — strategy ID and tunables.

Split out of the old single strategies/aft_rev.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.

IMPORTANT: scripts/diagnostics/archive/ab_test_v2_fixes.py monkey-patches
_MIN_BREAKOUT_PCT and _RVOL_BONUS_CAP directly on the PACKAGE object at
runtime, e.g. `aft_rev._MIN_BREAKOUT_PCT = 0.30` (via
`import strategies.aft_rev as aft_rev`). For that mutation to actually take
effect, evaluate.py must read these two via a fresh dotted lookup on the
live package object at call time, NOT via a `from constants import X`
binding captured once at import time (which would silently go stale and
never see the monkey-patch) — same pattern as strategies/vwap_pb.py,
strategy_router.py, and strategies/trend_cont.py earlier in this refactor.
STRATEGY_ID is not monkey-patched anywhere (confirmed via grep), so it's
read normally.
"""
from __future__ import annotations

STRATEGY_ID = "AFT_REV"

_MIN_BREAKOUT_PCT = 0.50   # min BOS clearance past the swing level, in % (2026-07-21, pending A/B)
_RVOL_BONUS_CAP   = 1.0    # was 2.0 — losers ran hotter RVOL than winners (2026-07-21, pending A/B)

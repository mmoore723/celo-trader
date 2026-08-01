"""
strategies/vwap_pb/constants.py — Strategy ID and tunable A/B-test knobs.

Split out of the old single strategies/vwap_pb.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.

IMPORTANT: archived diagnostic scripts (scripts/diagnostics/archive/
ab_test_vwap_pb.py, ab_test_candlestick_filter.py) monkey-patch several of
these knobs directly on the PACKAGE object at runtime, e.g.
`vwap_pb.BLOWTHROUGH_MIN_BARS = 5` before calling `vwap_pb.evaluate(...)`.
For that mutation to actually take effect, evaluate.py must read these
knobs via a fresh dotted lookup on the live package object at call time,
NOT via a `from constants import X` binding captured once at import time
(which would silently go stale and never see the monkey-patch). See
evaluate.py's own comment on this for the mechanics.
"""

STRATEGY_ID = "VWAP_PB"

# ── A/B test knobs (2026-07-15) ───────────────────────────────────────────────
# LIVE DEFAULT stays strict (5-of-5, no fast-recovery exception) — the 5-of-5
# guard is what cut VWAP_PB's audit loss from -$4,305/29 trades to -$495/5
# trades. A proposal came in to loosen back to 3-of-5 plus a "fast recovery"
# exception (allow entry when price pierced below VWAP then reclaimed
# instantly with momentum). That pattern is indistinguishable from the
# blowthrough crashes the guard exists to block, so it is NOT enabled by
# default. audit_strategies.py can flip these to A/B test before any live
# change is made — do not flip BLOWTHROUGH_MIN_BARS or FAST_RECOVERY_ENABLED
# directly in production without a passing backtest first.
BLOWTHROUGH_MIN_BARS  = 5      # of last 5 bars required on the correct side of VWAP
FAST_RECOVERY_ENABLED = False  # allow pierce-then-instant-reclaim as an exception
FAST_RECOVERY_MIN_BODY_PCT = 0.40   # candle body/range ratio required to count as "instant momentum"

# ── Candlestick rejection filter (2026-07-16) ────────────────────────────────
# OFF by default. When enabled, the VWAP-touch bar (prev) must show a genuine
# rejection candle — hammer for bullish touches, shooting star for bearish —
# not just a bar that happens to sit near the level. Rule-based (OHLC wick/body
# ratios), NOT machine learning; see candlestick_patterns.py. Distinguishes a
# defended touch from a touch that's actually a continuation candle in
# disguise. See ab_test_candlestick_filter.py before flipping this live.
CANDLESTICK_FILTER_ENABLED = False
CANDLESTICK_MIN_WICK_RATIO = 1.5   # loosened from 2.0 (2026-07-16) — first pass produced
                                   # 0 trades, conflicting with the 0.2% touch-proximity
                                   # band; 1.5x lets shorter genuine wicks still qualify.

# ── Pullback-count gate (2026-07-23, professional-strategy alignment audit) ───
# Published VWAP-pullback sources: the FIRST pullback to VWAP on a trend day
# has the highest win rate, the second is decent, by the third the trend is
# usually losing steam. This strategy had no concept of "which pullback" it
# was trading — a 4th or 5th touch scored the same confidence as the 1st.
# ON by default: MAX_PULLBACK_COUNT=2 means only the 1st and 2nd touch of a
# trend leg are tradeable; a 3rd+ touch is rejected. Set to None to disable
# (restores pre-2026-07-23 behavior — every touch treated equally).
MAX_PULLBACK_COUNT   = 2      # allow touch #1 and #2 only; reject #3+
_PULLBACK_LOOKBACK    = 60    # bars to search backward for the trend leg's start (safety cap)

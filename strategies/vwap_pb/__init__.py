"""
strategies/vwap_pb/__init__.py — VWAP Pullback (VWAP_PB)

Trend-continuation pullback to VWAP:
  Bullish: EMA50 + VWAP both rising, price taps VWAP (within 0.2%) then reclaims.
  Bearish: EMA50 + VWAP both falling, price taps VWAP then rejects.

Entry gates (2026-07-15 rework after 10% WR audit):
  • 5-of-5 blowthrough guard  • 0.2% touch proximity  • VWAP slope
  • EMA50 slope  • ADX ≥ 25 regime (enforced in strategy_router)

Session: 09:45–EOD  (skips opening chaos)

Split (2026-08-01, file-size cleanup) out of the old single
strategies/vwap_pb.py into constants.py, pullback.py, and evaluate.py; no
logic changed, only relocated.

The A/B-test knobs below (BLOWTHROUGH_MIN_BARS, FAST_RECOVERY_ENABLED, etc.)
are re-exported here BY VALUE from constants.py — that's deliberate and is
what makes THIS module's namespace (`strategies.vwap_pb`, i.e. what
`import strategies.vwap_pb as vwap_pb` gives you) the live, mutable home for
these knobs, exactly matching the old flat-file module's behavior where a
bare global name was always looked up against the module's own current
namespace. Archived diagnostic scripts do
`vwap_pb.BLOWTHROUGH_MIN_BARS = 3` — that assignment rebinds the name in
THIS __init__ module's __dict__, and evaluate.py reads it back via a live
dotted lookup on this same package object at call time (see evaluate.py's
docstring). Do not "simplify" this to `from .constants import *` re-exports
consumed elsewhere via `from strategies.vwap_pb.constants import ATTR` —
that would silently break the external-mutation contract.
"""

from strategies.vwap_pb.constants import (
    STRATEGY_ID,
    BLOWTHROUGH_MIN_BARS,
    FAST_RECOVERY_ENABLED,
    FAST_RECOVERY_MIN_BODY_PCT,
    CANDLESTICK_FILTER_ENABLED,
    CANDLESTICK_MIN_WICK_RATIO,
    MAX_PULLBACK_COUNT,
    _PULLBACK_LOOKBACK,
)
from strategies.vwap_pb.pullback import _count_prior_pullbacks
from strategies.vwap_pb.evaluate import evaluate

__all__ = [
    "STRATEGY_ID",
    "BLOWTHROUGH_MIN_BARS",
    "FAST_RECOVERY_ENABLED",
    "FAST_RECOVERY_MIN_BODY_PCT",
    "CANDLESTICK_FILTER_ENABLED",
    "CANDLESTICK_MIN_WICK_RATIO",
    "MAX_PULLBACK_COUNT",
    "_PULLBACK_LOOKBACK",
    "_count_prior_pullbacks",
    "evaluate",
]

"""Small, side-effect-free V2 strategy hypotheses."""

from research_v2.strategies.afternoon_reversal import AfternoonReversal, AfternoonReversalConfig
from research_v2.strategies.trend_continuation import TrendContinuation, TrendContinuationConfig
from research_v2.strategies.vwap_pullback import VWAPPullback, VWAPPullbackConfig

__all__ = [
    "AfternoonReversal", "AfternoonReversalConfig", "TrendContinuation", "TrendContinuationConfig",
    "VWAPPullback", "VWAPPullbackConfig",
]

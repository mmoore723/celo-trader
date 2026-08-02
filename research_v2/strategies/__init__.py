"""Small, side-effect-free V2 strategy hypotheses."""

from research_v2.strategies.trend_continuation import TrendContinuation, TrendContinuationConfig
from research_v2.strategies.vwap_pullback import VWAPPullback, VWAPPullbackConfig

__all__ = ["TrendContinuation", "TrendContinuationConfig", "VWAPPullback", "VWAPPullbackConfig"]

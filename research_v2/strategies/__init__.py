"""Small, side-effect-free V2 strategy hypotheses."""

from research_v2.strategies.afternoon_reversal import AfternoonReversal, AfternoonReversalConfig
from research_v2.strategies.fair_value_gap import FairValueGap, FairValueGapConfig
from research_v2.strategies.opening_range_pullback import OpeningRangePullback, OpeningRangePullbackConfig
from research_v2.strategies.opening_range_breakout import OpeningRangeBreakout, OpeningRangeBreakoutConfig
from research_v2.strategies.trend_continuation import TrendContinuation, TrendContinuationConfig
from research_v2.strategies.vwap_pullback import VWAPPullback, VWAPPullbackConfig
from research_v2.strategies.vwap_reversion_rth import VWAPReversionRTH, VWAPReversionRTHConfig
from research_v2.strategies.ema_pullback_rth import EMAPullbackRTH, EMAPullbackRTHConfig
from research_v2.strategies.turtle_soup_rth import TurtleSoupRTH, TurtleSoupRTHConfig
from research_v2.strategies.gap_fill_rth import GapFillRTH, GapFillRTHConfig
from research_v2.strategies.opening_momentum_rth import OpeningMomentumRTH, OpeningMomentumRTHConfig
from research_v2.strategies.supertrend_reversal import SuperTrendReversal, SuperTrendReversalConfig

__all__ = [
    "AfternoonReversal", "AfternoonReversalConfig", "FairValueGap", "FairValueGapConfig",
    "OpeningRangePullback", "OpeningRangePullbackConfig",
    "OpeningRangeBreakout", "OpeningRangeBreakoutConfig",
    "TrendContinuation", "TrendContinuationConfig",
    "VWAPPullback", "VWAPPullbackConfig",
    "VWAPReversionRTH", "VWAPReversionRTHConfig",
    "EMAPullbackRTH", "EMAPullbackRTHConfig",
    "TurtleSoupRTH", "TurtleSoupRTHConfig",
    "GapFillRTH", "GapFillRTHConfig",
    "OpeningMomentumRTH", "OpeningMomentumRTHConfig",
    "SuperTrendReversal", "SuperTrendReversalConfig",
]

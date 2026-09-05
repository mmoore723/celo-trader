"""Small, side-effect-free V2 strategy hypotheses."""

from research.engine.strategies.afternoon_reversal import AfternoonReversal, AfternoonReversalConfig
from research.engine.strategies.afternoon_compression_breakout import (
    AfternoonCompressionBreakout, AfternoonCompressionBreakoutConfig,
)
from research.engine.strategies.fair_value_gap import FairValueGap, FairValueGapConfig
from research.engine.strategies.opening_range_pullback import OpeningRangePullback, OpeningRangePullbackConfig
from research.engine.strategies.opening_range_breakout import OpeningRangeBreakout, OpeningRangeBreakoutConfig
from research.engine.strategies.trend_continuation import TrendContinuation, TrendContinuationConfig
from research.engine.strategies.vwap_pullback import VWAPPullback, VWAPPullbackConfig
from research.engine.strategies.vwap_reversion_rth import VWAPReversionRTH, VWAPReversionRTHConfig
from research.engine.strategies.ema_pullback_rth import EMAPullbackRTH, EMAPullbackRTHConfig
from research.engine.strategies.turtle_soup_rth import TurtleSoupRTH, TurtleSoupRTHConfig
from research.engine.strategies.gap_fill_rth import GapFillRTH, GapFillRTHConfig
from research.engine.strategies.opening_momentum_rth import OpeningMomentumRTH, OpeningMomentumRTHConfig
from research.engine.strategies.supertrend_reversal import SuperTrendReversal, SuperTrendReversalConfig
from research.engine.strategies.midday_breakdown import MiddayBreakdown, MiddayBreakdownConfig
from research.engine.strategies.orb_rsi_macd import ORBRsiMacdShort, ORBRsiMacdShortConfig
from research.engine.strategies.range_sweep_reclaim import (
    LongOnlyRangeSweepReclaim, RangeSweepReclaim, RangeSweepReclaimConfig,
)
from research.engine.strategies.impulse_anchored_vwap_pullback import (
    ImpulseAnchoredVwapConfig, ImpulseAnchoredVwapPullback,
)

__all__ = [
    "AfternoonCompressionBreakout", "AfternoonCompressionBreakoutConfig",
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
    "MiddayBreakdown", "MiddayBreakdownConfig",
    "ORBRsiMacdShort", "ORBRsiMacdShortConfig",
    "LongOnlyRangeSweepReclaim", "RangeSweepReclaim", "RangeSweepReclaimConfig",
    "ImpulseAnchoredVwapConfig", "ImpulseAnchoredVwapPullback",
]

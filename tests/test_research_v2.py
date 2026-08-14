"""Contract tests for the order-free V2 research foundation."""

from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from research.engine.data import load_csv, resample_regular_session
from research.engine.models import Bar, Side, Signal, Trade
from research.engine.reconciliation import ReferenceTrade, reconcile
from research.engine.ledger import load_trade_ledger, write_trade_ledger
from research.engine.regime import select_regimes
from research.engine.options import OptionQuote, OptionQuoteBook, load_option_quotes
from research.engine.option_markouts import (
    run_databento_cbbo_markouts, run_databento_cbbo_markouts_for_holds,
    run_databento_cbbo_markouts_for_labeled_signals,
    run_databento_cbbo_markouts_for_labeled_signals_and_holds,
    run_databento_cbbo_markouts_for_exit_plans,
    _active_decision_indexes, _window_matcher,
    run_option_markouts, strategy_signals,
)
from research.engine.indicators import confirmed_signals, macd_histogram, rsi
from research.jobs.compare_paid_rsi_macd_filters import (
    _completed_five_minute_signals, _distinct_breakout_episodes, select_training_variant,
)
from research.jobs.run_paid_spy_vwap_momentum_filters import _distinct_touch_episodes
from research.engine.exit_rules import (
    planned_exits, planned_one_minute_dynamic_exits, planned_noise_momentum_exits,
    planned_noise_momentum_failure_exits,
    planned_range_sweep_reclaim_exits,
)
from research.engine.noise_momentum import boundaries_by_timestamp, noise_momentum_signals
from research.engine.providers.alpaca import export_alpaca_csv
from research.engine.providers.databento import normalize_databento_cbbo_files
from research.engine.orb_retouch import one_minute_first_retouch_signals
from research.jobs.run_paid_databento_job import archive_filenames, batch_file_date, build_strategy, day_bars, day_bars_with_prior_close, extract_archive_file, manifest_filenames, summarize
from research.jobs.tune_paid_orb_holds import select_training_winner, segmented_summary
from research.jobs.tune_paid_strategy_holds import (
    bollinger_w_bottom_signals_by_completed_day, ema_signals_by_completed_day, non_overlapping_rows, select_robust_hold,
    squeeze_signals_by_completed_day, strategy_bars_for_hold_test,
)
from research.jobs.select_paid_markout_context import choose_context
from research.jobs.tune_paid_spy_vwap_contexts import select_three_period_context
from research.jobs.assess_paid_regime_context import _label_rows, select_context
from research.jobs.assess_paid_three_period_holds import assess_three_period_holds
from research.jobs.compare_paid_orb_exits import RULES, select_training_rule
from research.jobs.assess_paid_spy_range_sweep_reclaim import (
    portfolio_markouts as range_sweep_portfolio_markouts,
    select_training_variant as select_range_sweep_variant,
)
from research.jobs.assess_paid_spy_range_sweep_contexts import (
    context_markouts as range_sweep_context_markouts,
    select_direction_context as select_range_sweep_direction_context,
)
from research.jobs.assess_paid_fvg_contexts import _context_rows as fvg_context_markouts
from research.jobs.assess_paid_spy_range_sweep_momentum_contexts import (
    context_markouts as range_sweep_momentum_context_markouts,
    select_momentum_context as select_range_sweep_momentum_context,
)
from research.jobs.compare_paid_spy_range_sweep_long_exits import select_exit_rule as select_range_sweep_exit_rule
from research.jobs.compare_paid_one_minute_orb_call_exits import comparable_markouts
from research.engine.simulator import SimulationConfig, Simulator
from research.engine.strategies import (
    AfternoonReversal, AfternoonReversalConfig, FairValueGap, FairValueGapConfig,
    OpeningRangePullback, OpeningRangePullbackConfig,
    OpeningRangeBreakout, OpeningRangeBreakoutConfig,
    TrendContinuation, TrendContinuationConfig,
)
from research.engine.strategies import VWAPPullback, VWAPPullbackConfig, VWAPMeanReversion, VWAPMeanReversionConfig
from research.engine.strategies import TwoLegTrendPullback, TwoLegTrendPullbackConfig
from research.engine.strategies import (
    GapZScoreOpeningReversion, GapZScoreOpeningReversionConfig, build_gap_zscore_contexts,
)
from research.engine.strategies import VWAPFailedMoveReversion, VWAPFailedMoveReversionConfig, efficiency_ratio
from research.engine.strategies import SuperTrendReversal
from research.engine.strategies import ChannelBounce
from research.engine.strategies import BreakOfStructureMSS
from research.engine.strategies import LiquiditySweep
from research.engine.strategies import InverseFairValueGap
from research.engine.strategies import GapAndGo
from research.engine.strategies import LiveMiddayBreakdown
from research.engine.strategies.channel_bounce import _rvol_for_current_bar
from research.engine.strategies import EMAPullbackRTH, EMAPullbackRTHConfig
from research.engine.strategies import BollingerKeltnerSqueezeRTH, BollingerKeltnerSqueezeRTHConfig
from research.engine.strategies import SqueezeMomentumRTH, SqueezeMomentumRTHConfig
from research.engine.strategies import BollingerWBottomRTH, BollingerWBottomRTHConfig
from research.engine.strategies import RangeSweepReclaim, RangeSweepReclaimConfig
from research.engine.strategies import AfternoonCompressionBreakout, AfternoonCompressionBreakoutConfig
from research.engine.strategies import TurtleSoupRTH, TurtleSoupRTHConfig
from research.engine.strategies import GapFillRTH, GapFillRTHConfig
from research.engine.strategies import BreakoutPullbackContinuation, BreakoutPullbackContinuationConfig
from research.jobs.compare_paid_trend_contexts import strategy_bars as trend_context_strategy_bars
from research.engine.strategies import OpeningMomentumRTH, OpeningMomentumRTHConfig
from research.engine.supertrend_simulator import ReversalSimulationConfig, SuperTrendReversalSimulator
from research.engine.validation import ValidationConfig, validate
from research.engine.walk_forward import run_walk_forward
from strategy_router import route_signals


def _bar(minute: int, o: float, h: float, low: float, c: float) -> Bar:
    return Bar(datetime(2026, 1, 2, 9, 30) + timedelta(minutes=minute), o, h, low, c)


class _OneLong:
    strategy_id = "TEST_LONG"

    def evaluate(self, bars):
        if len(bars) != 2:
            return None
        last = bars[-1]
        return Signal(self.strategy_id, Side.LONG, last.timestamp, last.close, 98, 104, {"setup": "test"})


class _TrackingStrategy:
    strategy_id = "TRACKING"

    def __init__(self):
        self.seen = []

    def evaluate(self, bars):
        self.seen.append(len(bars))
        if len(bars) != 2:
            return None
        last = bars[-1]
        return Signal(self.strategy_id, Side.LONG, last.timestamp, last.close, 98, 104, {})


class _TrailingLong(_OneLong):
    def trailing_stop(self, signal, current_stop, bar, best_price):
        return 102


class ResearchV2Tests(unittest.TestCase):
    def test_range_sweep_selection_requires_positive_untouched_later_data(self) -> None:
        rows = {
            "baseline": [
                {"signal_time": "2026-06-01T10:00:00", "return_pct": 2.0},
                {"signal_time": "2026-06-02T10:00:00", "return_pct": 1.0},
                {"signal_time": "2026-07-02T10:00:00", "return_pct": -1.0},
            ] * 7,
            "tighter_quiet": [],
            "more_vwap_room": [],
        }
        result = select_range_sweep_variant(rows, date(2026, 7, 1), minimum_training_signals=10, minimum_later_signals=5)
        self.assertEqual("baseline", result["selected_variant"])
        self.assertFalse(result["later_data_passed"])

    def test_range_sweep_scorecard_excludes_overlapping_option_positions(self) -> None:
        rows = {
            "baseline": [
                {"entry_time": "2026-06-01T10:00:00", "exit_time": "2026-06-01T10:30:00"},
                {"entry_time": "2026-06-01T10:05:00", "exit_time": "2026-06-01T10:35:00"},
                {"entry_time": "2026-06-01T10:30:00", "exit_time": "2026-06-01T11:00:00"},
            ],
            "tighter_quiet": [],
            "more_vwap_room": [],
        }
        portfolio = range_sweep_portfolio_markouts(rows)
        self.assertEqual(
            ["2026-06-01T10:00:00", "2026-06-01T10:30:00"],
            [row["entry_time"] for row in portfolio["baseline"]],
        )

    def test_range_sweep_direction_context_filters_before_capacity(self) -> None:
        rows = [
            {"side": "short", "entry_time": "2026-06-01T10:00:00", "exit_time": "2026-06-01T10:30:00"},
            {"side": "long", "entry_time": "2026-06-01T10:05:00", "exit_time": "2026-06-01T10:35:00"},
        ]
        contexts = range_sweep_context_markouts(rows)
        self.assertEqual(1, len(contexts["both_directions"]))
        self.assertEqual(1, len(contexts["long_reclaims_only"]))
        self.assertEqual("long", contexts["long_reclaims_only"][0]["side"])

    def test_range_sweep_direction_selection_requires_untouched_later_data(self) -> None:
        def rows(day: str, side: str, value: float, count: int):
            return [{"signal_time": f"{day}T10:00:00", "return_pct": value, "side": side} for _ in range(count)]
        contexts = {
            "both_directions": rows("2026-06-01", "long", 1, 20) + rows("2026-07-02", "long", -1, 10),
            "long_reclaims_only": rows("2026-06-01", "long", 3, 20) + rows("2026-07-02", "long", -1, 10),
            "short_reclaims_only": rows("2026-06-01", "short", 2, 20) + rows("2026-07-02", "short", 2, 10),
        }
        selection = select_range_sweep_direction_context(contexts, date(2026, 7, 1))
        self.assertEqual("long_reclaims_only", selection["selected_context"])
        self.assertFalse(selection["later_data_passed"])

    def test_fvg_contexts_apply_capacity_after_direction_filter(self) -> None:
        rows = [
            {"side": "short", "signal_time": "2026-06-01T10:00:00", "entry_time": "2026-06-01T10:00:00", "exit_time": "2026-06-01T10:30:00"},
            {"side": "long", "signal_time": "2026-06-01T10:05:00", "entry_time": "2026-06-01T10:05:00", "exit_time": "2026-06-01T10:35:00"},
            {"side": "long", "signal_time": "2026-06-01T10:10:00", "entry_time": "2026-06-01T10:10:00", "exit_time": "2026-06-01T10:40:00"},
        ]
        contexts = fvg_context_markouts(rows)
        self.assertEqual(["2026-06-01T10:00:00"], [row["entry_time"] for row in contexts["all_fvg"]])
        self.assertEqual(["2026-06-01T10:05:00"], [row["entry_time"] for row in contexts["long_only"]])

    def test_range_sweep_momentum_contexts_filter_before_capacity(self) -> None:
        rows = [
            {"side": "short", "entry_time": "2026-06-01T10:00:00", "exit_time": "2026-06-01T10:30:00",
             "prior_rsi_14": 50.0, "macd_histogram_12_26_9": .1, "prior_macd_histogram_12_26_9": .2},
            {"side": "long", "entry_time": "2026-06-01T10:05:00", "exit_time": "2026-06-01T10:35:00",
             "prior_rsi_14": 35.0, "macd_histogram_12_26_9": -.1, "prior_macd_histogram_12_26_9": -.2},
            {"side": "long", "entry_time": "2026-06-01T10:10:00", "exit_time": "2026-06-01T10:40:00",
             "prior_rsi_14": 42.0, "macd_histogram_12_26_9": -.2, "prior_macd_histogram_12_26_9": -.3},
        ]
        contexts = range_sweep_momentum_context_markouts(rows)
        self.assertEqual(1, len(contexts["all_reclaims"]))
        self.assertEqual(["2026-06-01T10:05:00"], [row["entry_time"] for row in contexts["rsi_and_macd_turn"]])

    def test_range_sweep_momentum_selection_requires_positive_later_data(self) -> None:
        def rows(day: str, value: float, count: int) -> list[dict[str, object]]:
            return [{"signal_time": f"{day}T10:00:00", "return_pct": value} for _ in range(count)]

        contexts = {
            "all_reclaims": rows("2026-06-01", 1.0, 20) + rows("2026-07-02", 1.0, 10),
            "soft_rsi_exhaustion": rows("2026-06-01", 2.0, 20) + rows("2026-07-02", -1.0, 10),
            "macd_histogram_turn": rows("2026-06-01", 1.5, 20) + rows("2026-07-02", .5, 10),
            "rsi_and_macd_turn": [],
        }
        selection = select_range_sweep_momentum_context(contexts, date(2026, 7, 1))
        self.assertEqual("soft_rsi_exhaustion", selection["selected_context"])
        self.assertFalse(selection["later_data_passed"])

    def test_range_sweep_exit_selection_requires_positive_later_data(self) -> None:
        def row(day: str, pct: float) -> dict[str, object]:
            return {"signal_time": f"{day}T10:30:00", "return_pct": pct}
        marks = {
            rule: [row("2026-06-01", 1.0)] * 10 + [row("2026-07-10", 1.0)] * 10
            for rule in ("fixed_30m", "vwap_touch_or_stop_60m", "vwap_close_or_stop_60m")
        }
        marks["vwap_touch_or_stop_60m"] = [row("2026-06-01", 3.0)] * 10 + [row("2026-07-10", -1.0)] * 10
        selection = select_range_sweep_exit_rule(marks, date(2026, 7, 1))
        self.assertEqual("vwap_touch_or_stop_60m", selection["selected_exit_rule"])
        self.assertFalse(selection["later_data_passed"])

    def test_range_sweep_reclaim_requires_quiet_market_sweep_then_close_back_inside(self) -> None:
        start = datetime(2026, 1, 2, 10, 0)
        bars = []
        # A small back-and-forth range provides the level to sweep.
        for index in range(21):
            close = 100.0 + (.08 if index % 2 else -.08)
            bars.append(Bar(start + timedelta(minutes=index), close, close + .10, close - .10, close, 1000))
        # The next bar sweeps the old range low. The following completed
        # green candle closes back inside it but remains below VWAP.
        bars.append(Bar(start + timedelta(minutes=21), 99.55, 99.62, 99.38, 99.48, 1000))
        bars.append(Bar(start + timedelta(minutes=22), 99.50, 99.92, 99.45, 99.86, 1000))
        strategy = RangeSweepReclaim(RangeSweepReclaimConfig(
            range_bars=20, minimum_sweep_atr=.10, minimum_vwap_room_atr=.01,
            minimum_reward_risk=.05,
        ))
        signal = None
        for index in range(1, len(bars) + 1):
            signal = strategy.evaluate(bars[:index])
            if signal is not None:
                break
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(Side.LONG, signal.side)
        self.assertEqual("quiet_range_low_swept_then_reclaimed", signal.features["trigger"])

    def test_range_sweep_reclaim_rejects_directional_market(self) -> None:
        start = datetime(2026, 1, 2, 10, 0)
        bars = [
            Bar(start + timedelta(minutes=index), 100 + index * .1, 100.12 + index * .1,
                99.98 + index * .1, 100.1 + index * .1, 1000)
            for index in range(23)
        ]
        self.assertIsNone(RangeSweepReclaim().evaluate(bars))

    def test_afternoon_compression_breakout_requires_compact_box_then_aligned_break(self) -> None:
        start = datetime(2026, 1, 2, 12, 0)
        config = AfternoonCompressionBreakoutConfig(
            fast_ema=3, slow_ema=5, atr_bars=3, min_compression_bars=3,
            compression_start=time(12, 30), compression_end=time(12, 33), entry_end=time(13, 0),
            max_compression_pct=.01,
        )
        strategy = AfternoonCompressionBreakout(config)
        bars = []
        # Indicator warmup and an upwardly aligned market before the compact box.
        for index, close in enumerate((100.0, 100.1, 100.2, 100.25, 100.3, 100.35)):
            bars.append(Bar(start + timedelta(minutes=index), close - .02, close + .04, close - .04, close, 1000))
            self.assertIsNone(strategy.evaluate(bars))
        box_start = datetime(2026, 1, 2, 12, 30)
        for index, close in enumerate((100.35, 100.37, 100.36)):
            bars.append(Bar(box_start + timedelta(minutes=index), close, 100.40, 100.32, close, 1000))
            self.assertIsNone(strategy.evaluate(bars))
        # The first post-box candle closes cleanly above the 12:30–12:32 high.
        bars.append(Bar(datetime(2026, 1, 2, 12, 33), 100.38, 100.58, 100.36, 100.55, 1000))
        signal = strategy.evaluate(bars)
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(Side.LONG, signal.side)
        self.assertEqual("afternoon_compact_range_upward_expansion", signal.features["trigger"])

    def test_failed_move_reversion_requires_quiet_stretch_then_reclaim(self) -> None:
        start = datetime(2026, 1, 2, 10, 15)
        # Alternating prices create a quiet 20-minute context around VWAP.
        bars = []
        for index in range(21):
            close = 100.0 + (.04 if index % 2 else -.04)
            bars.append(Bar(start + timedelta(minutes=index), close, close + .08, close - .08, close, 1000))
        # A real downside extension, then a bullish close reclaiming its band.
        bars.append(Bar(start + timedelta(minutes=21), 99.55, 99.58, 99.45, 99.50, 1000))
        bars.append(Bar(start + timedelta(minutes=22), 99.52, 99.92, 99.50, 99.90, 1000))
        strategy = VWAPFailedMoveReversion(VWAPFailedMoveReversionConfig(
            regime_bars=20, stretch_atr=.8, minimum_reward_risk=.1,
        ))
        signal = None
        for index in range(1, len(bars) + 1):
            signal = strategy.evaluate(bars[:index])
            if signal is not None:
                break
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(Side.LONG, signal.side)
        self.assertEqual("quiet_market_lower_vwap_stretch_reclaimed", signal.features["trigger"])

    def test_failed_move_reversion_rejects_directional_market(self) -> None:
        start = datetime(2026, 1, 2, 9, 30)
        bars = [Bar(start + timedelta(minutes=index), 100 + index * .1, 100.12 + index * .1,
                    99.98 + index * .1, 100.1 + index * .1, 1000) for index in range(24)]
        self.assertGreater(efficiency_ratio([bar.close for bar in bars[-21:]]), .4)
        self.assertIsNone(VWAPFailedMoveReversion().evaluate(bars))
    def test_breakout_pullback_continuation_requires_all_three_steps(self) -> None:
        """A break alone is not an entry; it needs retest then fresh proof."""
        start = datetime(2026, 1, 2, 9, 30)
        config = BreakoutPullbackContinuationConfig(
            range_bars=3, fast_ema=3, slow_ema=5, atr_bars=3,
            entry_start=time(9, 55), entry_end=time(15, 0),
        )
        strategy = BreakoutPullbackContinuation(config)
        bars = []
        # Calm range, then an upward break.  No signal may occur yet.
        for index, close in enumerate((100, 100.1, 100.0, 100.2, 100.1, 100.2, 100.4, 100.8)):
            bars.append(Bar(start + timedelta(minutes=index * 5), close, close + .12, close - .12, close, 1000))
            self.assertIsNone(strategy.evaluate(bars))
        # Retest the broken level: still no signal.
        bars.append(Bar(start + timedelta(minutes=40), 100.75, 100.82, 100.32, 100.58, 1000))
        self.assertIsNone(strategy.evaluate(bars))
        # A new completed bullish candle proves the retest held.
        bars.append(Bar(start + timedelta(minutes=45), 100.6, 100.95, 100.55, 100.9, 1000))
        signal = strategy.evaluate(bars)
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(Side.LONG, signal.side)
        self.assertEqual("up_break_first_retest_confirmation", signal.features["trigger"])

    def test_breakout_pullback_continuation_emits_once_per_session(self) -> None:
        start = datetime(2026, 1, 2, 9, 30)
        config = BreakoutPullbackContinuationConfig(
            range_bars=3, fast_ema=3, slow_ema=5, atr_bars=3,
            entry_start=time(9, 55), entry_end=time(15, 0),
        )
        strategy = BreakoutPullbackContinuation(config)
        bars = []
        for index, close in enumerate((100, 100.1, 100.0, 100.2, 100.1, 100.2, 100.4, 100.8, 100.58, 100.9, 101.3, 101.8)):
            bars.append(Bar(start + timedelta(minutes=index * 5), close, close + .12, close - .12, close, 1000))
            strategy.evaluate(bars)
        # The first signal has already happened; later bars cannot produce
        # another same-day entry from the same or a new sequence.
        self.assertIsNone(strategy.evaluate(bars))

    def test_paid_trend_contexts_uses_completed_five_minute_bars(self) -> None:
        """The paid quote context study must match the trend strategy cadence."""
        start = datetime(2026, 1, 2, 9, 30)
        one_minute = tuple(
            Bar(start + timedelta(minutes=index), 100, 101, 99, 100 + index * .01, 1000)
            for index in range(10)
        )
        bars = trend_context_strategy_bars(one_minute)
        self.assertEqual(2, len(bars))
        self.assertEqual((time(9, 30), time(9, 35)), tuple(bar.timestamp.time() for bar in bars))

    def test_channel_bounce_never_uses_future_bars_to_confirm_a_signal(self) -> None:
        # A channel screen may inspect only the supplied completed history. A
        # later bar that would make an old low a better pivot cannot create a
        # retroactive signal at an earlier timestamp.
        start = datetime(2026, 1, 2, 9, 30)
        bars = tuple(
            Bar(start + timedelta(minutes=index * 5), 100 + index * .1,
                100.3 + index * .1, 99.8 + index * .1, 100.1 + index * .1, 1000)
            for index in range(30)
        )
        strategy = ChannelBounce()
        early = strategy.evaluate(bars[:-1])
        late = strategy.evaluate(bars)
        if early is not None:
            self.assertLess(early.timestamp, bars[-1].timestamp)
        if late is not None:
            self.assertEqual(bars[-1].timestamp, late.timestamp)

    def test_bos_mss_does_not_emit_before_its_current_completed_bar(self) -> None:
        start = datetime(2026, 1, 2, 9, 30)
        bars = tuple(
            Bar(start + timedelta(minutes=index * 5), 100 + index * .1,
                100.3 + index * .1, 99.8 + index * .1, 100.1 + index * .1, 1000)
            for index in range(30)
        )
        candidate = BreakOfStructureMSS().evaluate(bars)
        if candidate is not None:
            self.assertEqual(bars[-1].timestamp, candidate.timestamp)

    def test_liquidity_sweep_only_emits_on_its_confirmation_bar(self) -> None:
        start = datetime(2026, 1, 2, 9, 30)
        bars = tuple(
            Bar(start + timedelta(minutes=index), 100 + index * .01,
                100.2 + index * .01, 99.8 + index * .01, 100.05 + index * .01, 1000)
            for index in range(35)
        )
        candidate = LiquiditySweep().evaluate(bars)
        if candidate is not None:
            self.assertEqual(bars[-1].timestamp, candidate.timestamp)

    def test_inverse_fvg_only_emits_on_its_current_completed_bar(self) -> None:
        start = datetime(2026, 1, 2, 9, 30)
        bars = tuple(
            Bar(start + timedelta(minutes=index), 100 + index * .01,
                100.2 + index * .01, 99.8 + index * .01, 100.05 + index * .01, 1000)
            for index in range(45)
        )
        candidate = InverseFairValueGap().evaluate(bars)
        if candidate is not None:
            self.assertEqual(bars[-1].timestamp, candidate.timestamp)

    def test_gap_and_go_only_emits_on_its_current_completed_bar(self) -> None:
        start = datetime(2026, 1, 2, 9, 30)
        previous = Bar(start - timedelta(days=1), 100, 101, 99, 100, 1000)
        today = tuple(
            Bar(start + timedelta(minutes=index * 5), 101 + index * .1,
                101.3 + index * .1, 100.8 + index * .1, 101.1 + index * .1, 1000)
            for index in range(4)
        )
        candidate = GapAndGo().evaluate((previous, *today))
        if candidate is not None:
            self.assertEqual(today[-1].timestamp, candidate.timestamp)

    def test_live_midday_breakdown_only_emits_on_its_current_completed_bar(self) -> None:
        start = datetime(2026, 1, 2, 9, 30)
        bars = tuple(
            Bar(start + timedelta(minutes=index * 5), 100 - index * .1,
                100.2 - index * .1, 99.8 - index * .1, 99.95 - index * .1, 1000)
            for index in range(45)
        )
        candidate = LiveMiddayBreakdown().evaluate(bars)
        if candidate is not None:
            self.assertEqual(bars[-1].timestamp, candidate.timestamp)

    def test_rvol_fallback_does_not_read_later_bars(self) -> None:
        start = datetime(2026, 1, 2, 9, 30)
        observed = Bar(start, 100, 101, 99, 100, 100)
        prior = tuple(Bar(start - timedelta(minutes=20 - index), 100, 101, 99, 100, 100)
                      for index in range(20))
        future = tuple(Bar(start + timedelta(minutes=index + 1), 100, 101, 99, 100, 10_000)
                       for index in range(20))
        with_future = _rvol_for_current_bar((*prior, observed, *future), observed, 10)
        without_future = _rvol_for_current_bar((*prior, observed), observed, 10)
        self.assertEqual(without_future, with_future)
    def test_quote_window_matcher_merges_without_expanding_boundaries(self) -> None:
        start = datetime(2026, 1, 2, 10, 0)
        matcher = _window_matcher(((start, start + timedelta(minutes=1)),
                                   (start + timedelta(minutes=1), start + timedelta(minutes=2)),
                                   (start + timedelta(minutes=5), start + timedelta(minutes=6))))
        self.assertTrue(matcher(start))
        self.assertTrue(matcher(start + timedelta(minutes=2)))
        self.assertFalse(matcher(start + timedelta(minutes=3)))
        self.assertTrue(matcher(start + timedelta(minutes=5, seconds=30)))
        self.assertFalse(matcher(start - timedelta(microseconds=1)))

    def test_active_decision_indexes_keeps_exact_entry_window_boundaries(self) -> None:
        start = datetime(2026, 1, 2, 10, 0)
        starts = (start, start + timedelta(minutes=1), start + timedelta(minutes=5))
        self.assertEqual([0], list(_active_decision_indexes(starts, start + timedelta(seconds=30), timedelta(minutes=1))))
        self.assertEqual([0, 1], list(_active_decision_indexes(starts, start + timedelta(minutes=1), timedelta(minutes=1))))
        self.assertEqual([], list(_active_decision_indexes(starts, start + timedelta(minutes=2, microseconds=1), timedelta(minutes=1))))

    def test_noise_momentum_uses_only_prior_fourteen_sessions(self) -> None:
        # Every history session moves exactly 1% from its open by 10:00.  On
        # session 15, a 2% move at the same clock is outside the causal upper
        # boundary and may signal long.  No future session participates.
        history = []
        for day in range(14):
            start = datetime(2026, 1, 2, 9, 30) + timedelta(days=day)
            # Dates need only be distinct for this pure domain test.
            history.extend((
                Bar(start, 100, 100, 100, 100),
                Bar(start.replace(hour=10), 100, 101, 100, 101),
                Bar(start.replace(hour=15, minute=59), 101, 101, 101, 101),
            ))
        current = datetime(2026, 1, 16, 9, 30)
        today = (
            Bar(current, 100, 100, 100, 100),
            Bar(current.replace(hour=10), 100, 103, 100, 103),
            Bar(current.replace(hour=15, minute=59), 103, 103, 103, 103),
        )
        signals = noise_momentum_signals((*history, *today))
        self.assertEqual(1, len(signals))
        self.assertEqual(Side.LONG, signals[0].side)
        self.assertEqual(current.replace(hour=10), signals[0].timestamp)
        bounds = boundaries_by_timestamp((*history, *today))
        self.assertLess(bounds[signals[0].timestamp][1], 103)

    def test_noise_momentum_exit_waits_for_next_minute_after_half_hour_close(self) -> None:
        signal = Signal("NOISE", Side.LONG, _bar(30, 102, 102, 102, 102).timestamp, 102, 99, 105, {})
        entry = _bar(31, 102, 102, 102, 102)
        later = _bar(60, 101, 101, 100, 101)
        plans = planned_noise_momentum_exits(
            (entry, later, _bar(389, 101, 101, 101, 101)), signal, entry,
            boundaries={later.timestamp: (99, 101.5)},
        )
        self.assertEqual(later.timestamp + timedelta(minutes=1), plans["current_band"].time)
        self.assertEqual("lost_current_noise_boundary", plans["current_band"].reason)

    def test_noise_momentum_failure_exit_uses_frozen_entry_boundary(self) -> None:
        signal = Signal(
            "NOISE", Side.LONG, _bar(30, 102, 103, 102, 103).timestamp,
            103, 101, 107, {"noise_lower": 99.0, "noise_upper": 102.0},
        )
        entry = _bar(31, 103, 103, 102.5, 102.8)
        first_failure = _bar(32, 102.8, 102.9, 101.7, 101.9)
        second_failure = _bar(33, 101.9, 102.0, 101.2, 101.5)
        plans = planned_noise_momentum_failure_exits(
            (entry, first_failure, second_failure), signal, entry,
        )
        self.assertEqual(
            first_failure.timestamp + timedelta(minutes=1), plans["failed_break_1m"].time,
        )
        self.assertEqual(
            second_failure.timestamp + timedelta(minutes=1), plans["failed_break_2m"].time,
        )

    def test_noise_momentum_failure_exit_rejects_missing_boundary(self) -> None:
        signal = Signal("NOISE", Side.SHORT, _bar(30, 98, 98, 97, 97).timestamp, 97, 99, 95, {})
        with self.assertRaisesRegex(ValueError, "noise_lower"):
            planned_noise_momentum_failure_exits((_bar(31, 97, 98, 96, 97),), signal, _bar(31, 97, 98, 96, 97))

    def test_one_minute_orb_retouch_requires_breakout_then_later_clean_touch(self) -> None:
        # The first 15 minutes create a 100/90 range.  A close outside the
        # range only arms the setup; the following clean touch creates it.
        opening = tuple(_bar(index, 95, 100, 90, 95) for index in range(15))
        breakout = _bar(15, 100, 102, 100, 101)
        retouch = _bar(16, 101, 102, 99.98, 101)
        signals = one_minute_first_retouch_signals((*opening, breakout, retouch))
        self.assertEqual(1, len(signals))
        signal = signals[0]
        self.assertEqual(Side.LONG, signal.side)
        self.assertEqual(retouch.timestamp, signal.timestamp)
        self.assertEqual(100, signal.entry_reference)
        self.assertEqual(90, signal.stop)

    def test_one_minute_orb_retouch_rejects_a_cross_through_range_level(self) -> None:
        opening = tuple(_bar(index, 95, 100, 90, 95) for index in range(15))
        breakout = _bar(15, 100, 102, 100, 101)
        # It reaches the level but then breaks below its allowed retest zone,
        # so this is a failed breakout, not a clean long entry.
        failed_touch = _bar(16, 101, 102, 99.80, 100)
        self.assertEqual((), one_minute_first_retouch_signals((*opening, breakout, failed_touch)))

    def test_rsi_macd_confirmations_only_use_completed_history(self) -> None:
        self.assertIsNone(rsi([100.0] * 14))
        self.assertEqual(100.0, rsi(list(range(1, 17))))
        self.assertIsNone(macd_histogram(list(range(1, 34))))
        bars = tuple(_bar(index * 5, 100 + index, 101 + index, 99 + index, 100 + index)
                     for index in range(40))
        class SignalAfterThirty:
            strategy_id = "FILTER_TEST"
            def evaluate(self, history):
                if len(history) != 35:
                    return None
                last = history[-1]
                return Signal(self.strategy_id, Side.LONG, last.timestamp, last.close,
                              last.close - 1, last.close + 2, {})
        filtered = confirmed_signals(bars, SignalAfterThirty(), require_rsi=True, require_macd=True)
        self.assertEqual(1, len(filtered))
        self.assertIn("rsi_14", filtered[0].features)
        self.assertIn("macd_histogram_12_26_9", filtered[0].features)

    def test_indicators_retain_causal_history_not_short_rolling_windows(self) -> None:
        # The long positive history must still influence an immediately later
        # decline. A 14-value rolling RSI would incorrectly discard it.
        closes = [100.0 + index for index in range(30)] + [129.0 - index for index in range(8)]
        self.assertGreater(rsi(closes) or 0, 50.0)
        # A 12/26/9 MACD is not fully formed until 34 completed closes.
        self.assertIsNone(macd_histogram(list(range(33))))
        self.assertIsNotNone(macd_histogram(list(range(34))))

    def test_indicator_warmup_does_not_leak_into_strategy_session(self) -> None:
        prior = tuple(_bar(-200 + index * 5, 80 + index, 81 + index, 79 + index, 80 + index)
                      for index in range(40))
        day = tuple(_bar(index * 5, 120 + index, 121 + index, 119 + index, 120 + index)
                    for index in range(4))
        class FirstDayBarSignal:
            strategy_id = "SESSION_ONLY"
            def evaluate(self, history):
                if len(history) != 1:
                    return None
                bar = history[-1]
                return Signal(self.strategy_id, Side.LONG, bar.timestamp, bar.close,
                              bar.close - 1, bar.close + 2, {})
        results = confirmed_signals(day, FirstDayBarSignal(), indicator_history=prior, require_rsi=True)
        self.assertEqual(1, len(results))

    def test_rsi_macd_selector_does_not_choose_on_later_dates(self) -> None:
        def rows(day: str, result: float, count: int):
            return [{"signal_time": f"{day}T10:00:00", "return_pct": result}] * count
        markouts = {
            "base": rows("2026-01-02", 1, 15) + rows("2026-03-02", 1, 10),
            "rsi_14_aligned": rows("2026-01-02", 3, 15) + rows("2026-03-02", -1, 10),
            "macd_12_26_9_aligned": rows("2026-01-02", 2, 15) + rows("2026-03-02", 2, 10),
            "rsi_and_macd_aligned": rows("2026-01-02", 0.5, 15) + rows("2026-03-02", 4, 10),
        }
        selection = select_training_variant(markouts, date(2026, 3, 1))
        self.assertEqual("rsi_14_aligned", selection["selected_variant"])
        self.assertFalse(selection["later_data_passed"])

    def test_rsi_macd_selector_rejects_negative_earlier_period(self) -> None:
        def rows(day: str, result: float, count: int):
            return [{"signal_time": f"{day}T10:00:00", "return_pct": result}] * count
        markouts = {
            "base": rows("2026-01-02", -1, 15) + rows("2026-03-02", 2, 10),
            "rsi_14_aligned": rows("2026-01-02", -2, 15) + rows("2026-03-02", 3, 10),
            "macd_12_26_9_aligned": [],
            "rsi_and_macd_aligned": [],
        }
        selection = select_training_variant(markouts, date(2026, 3, 1))
        self.assertIsNone(selection["selected_variant"])
        self.assertEqual("no_variant_with_enough_positive_earlier_data", selection["reason"])

    def test_spy_vwap_three_period_selector_does_not_select_using_june_or_july(self) -> None:
        def rows(day: str, result: float, count: int, side: str = "long"):
            return [{"signal_time": f"{day}T11:15:00", "side": side, "return_pct": result}] * count
        # May picks late-morning long. June rejects it; July's positive result
        # must not retroactively rescue or change that selected context.
        data = (rows("2026-05-12", 3, 10) + rows("2026-06-10", -2, 10)
                + rows("2026-07-10", 5, 10) + rows("2026-05-12", 1, 10, "short"))
        selection = select_three_period_context(data)
        self.assertEqual("long_late_morning", selection["selected_context"])
        self.assertFalse(selection["june_passed"])
        self.assertFalse(selection["decision"] == "paper_candidate")

    def test_three_period_hold_assessment_selects_on_may_only(self) -> None:
        def rows(day: str, result: float, count: int):
            return [{"signal_time": f"{day}T11:00:00", "return_pct": result}] * count
        marks = {
            30: rows("2026-05-10", 1, 15) + rows("2026-06-10", 2, 10) + rows("2026-07-10", 2, 10),
            60: rows("2026-05-10", 3, 15) + rows("2026-06-10", -2, 10) + rows("2026-07-10", 9, 10),
        }
        assessment = assess_three_period_holds(marks)
        self.assertEqual(60, assessment["selected_hold_minutes"])
        self.assertFalse(assessment["june_passed"])
        self.assertEqual("reject", assessment["decision"])
    def test_paid_markout_context_selection_uses_training_before_later(self) -> None:
        rows = [
            {"signal_time": "2026-01-02T10:00:00", "side": "long", "return_pct": 4},
            {"signal_time": "2026-01-03T10:00:00", "side": "long", "return_pct": 3},
            {"signal_time": "2026-01-04T10:00:00", "side": "short", "return_pct": -2},
            {"signal_time": "2026-01-05T10:00:00", "side": "short", "return_pct": -1},
            {"signal_time": "2026-02-02T10:00:00", "side": "long", "return_pct": -3},
        ]
        selection = choose_context(rows, date(2026, 2, 1), minimum_training_trades=2)
        self.assertEqual("long_all_day", selection["selected_context"])
        self.assertFalse(selection["later_passed"])

    def test_paid_markout_context_selection_rejects_a_losing_training_bucket(self) -> None:
        def rows(day: str, result: float, count: int, side: str = "long"):
            return [{"signal_time": f"{day}T10:00:00", "side": side, "return_pct": result}] * count
        # Both buckets have adequate observations, but neither earned its
        # place in the earlier period.  A positive later run cannot rescue it.
        data = rows("2026-01-02", -1, 12) + rows("2026-03-02", 4, 12)
        selection = choose_context(data, date(2026, 3, 1), minimum_training_trades=10)
        self.assertIsNone(selection["selected_context"])
    def test_empty_production_strategy_set_never_routes_a_signal(self) -> None:
        # This must return before indicator construction: an empty set is the
        # deliberate "no validated strategy" safety state, unlike None which
        # means run the router's entire research universe.
        import pandas as pd
        frame = pd.DataFrame({"time": pd.date_range("2026-01-02 09:30", periods=2, freq="5min")})
        self.assertEqual([], route_signals(frame, "TSLA", enabled_strategies=set(), quiet=True))

    def test_paid_batch_helpers_only_accept_daily_cbbo_files(self) -> None:
        self.assertEqual(date(2026, 7, 8), batch_file_date("opra-pillar-20260708.cbbo-1m.csv.zst"))
        self.assertIsNone(batch_file_date("manifest.json"))
        bars = (_bar(0, 100, 101, 99, 100),)
        dataset = type("Dataset", (), {"bars": bars})()
        self.assertEqual(bars, day_bars(dataset, date(2026, 1, 2)))
        self.assertEqual((), day_bars(dataset, date(2026, 1, 3)))
        prior = _bar(-5, 99, 100, 98, 99)
        later = _bar(5, 101, 102, 100, 101)
        gap_dataset = type("Dataset", (), {"bars": (prior, *bars, later)})()
        self.assertEqual((prior, *bars, later), day_bars_with_prior_close(gap_dataset, date(2026, 1, 2)))
        self.assertEqual(1, summarize(({"return_pct": 2.5},))["measured_signals"])
        manifest = {"files": [{"filename": "manifest.json"},
                              {"filename": "opra-pillar-20260708.cbbo-1m.csv.zst"}]}
        self.assertEqual(("opra-pillar-20260708.cbbo-1m.csv.zst",), manifest_filenames(manifest))

    def test_paid_archive_lists_only_daily_cbbo_files(self) -> None:
        import zipfile
        with TemporaryDirectory() as directory:
            archive = Path(directory) / "paid.zip"
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr("metadata.json", "{}")
                handle.writestr("opra-pillar-20260708.cbbo-1m.csv.zst", "quotes")
            self.assertEqual(("opra-pillar-20260708.cbbo-1m.csv.zst",), archive_filenames(archive))

    def test_paid_batch_folder_lists_and_stages_only_daily_cbbo_files(self) -> None:
        with TemporaryDirectory() as directory:
            source = Path(directory) / "delivery"
            source.mkdir()
            filename = "opra-pillar-20260708.cbbo-1m.csv.zst"
            (source / filename).write_text("paid quotes", encoding="utf-8")
            (source / "manifest.json").write_text("{}", encoding="utf-8")
            self.assertEqual((filename,), archive_filenames(source))
            staged = extract_archive_file(source, filename, Path(directory) / "scratch" / filename)
            self.assertEqual("paid quotes", staged.read_text(encoding="utf-8"))
            self.assertTrue((source / filename).is_file())

    def test_paid_runner_selects_distinct_orb_hypotheses(self) -> None:
        self.assertEqual("V2_ORB_PULLBACK", build_strategy("orb_pullback").strategy_id)
        self.assertEqual(0.0005, build_strategy("v2_orb_pullback").config.retest_tolerance_pct)
        self.assertEqual("V2_VWAP_PULLBACK", build_strategy("vwap_pullback").strategy_id)
        self.assertEqual("V2_TREND_CONT", build_strategy("trend_continuation").strategy_id)
        self.assertEqual("V2_AFTERNOON_REVERSAL", build_strategy("afternoon_reversal").strategy_id)
        self.assertEqual("V2_GAP_FILL_RTH", build_strategy("gap_fill_rth").strategy_id)
        self.assertEqual("V2_TURTLE_SOUP_RTH", build_strategy("turtle_soup_rth").strategy_id)
        self.assertEqual("V2_EMA_PULLBACK_RTH", build_strategy("ema_pullback_rth").strategy_id)

    def test_paid_markout_rejects_invalid_signal_cap(self) -> None:
        with self.assertRaises(ValueError):
            run_databento_cbbo_markouts_for_holds(
                (_bar(0, 100, 101, 99, 100),), (), _OneLong(), "TSLA",
                max_signals=0,
            )
        with self.assertRaises(ValueError):
            run_databento_cbbo_markouts_for_exit_plans(
                (_bar(0, 100, 101, 99, 100),), (Path("unused.csv"),), _OneLong(), "TSLA",
                {"fixed_90m": {}}, max_signals=0,
            )

    def test_paid_hold_tuner_selects_training_only_then_checks_holdout(self) -> None:
        def row(day: str, pct: float) -> dict[str, object]:
            return {"signal_time": f"{day}T10:00:00", "return_pct": pct}
        # 30 min wins the earlier data, but loses the untouched segment.
        marks = {
            30: [row("2026-01-02", 10.0)] * 15 + [row("2026-03-03", -1.0)] * 10,
            60: [row("2026-01-02", 5.0)] * 15 + [row("2026-03-03", 2.0)] * 10,
            90: [row("2026-01-02", 1.0)] * 15 + [row("2026-03-03", 1.0)] * 10,
        }
        summary = segmented_summary(marks[60], date(2026, 3, 1))
        self.assertEqual(15, summary["training"]["measured_signals"])
        self.assertEqual(10, summary["holdout"]["measured_signals"])
        chosen = select_training_winner(marks, date(2026, 3, 1))
        self.assertEqual(30, chosen["selected_hold_minutes"])
        self.assertFalse(chosen["holdout_passed"])

    def test_robust_paid_hold_tuner_requires_typical_gain_on_later_data(self) -> None:
        def row(day: str, pct: float) -> dict[str, object]:
            return {"signal_time": f"{day}T10:00:00", "return_pct": pct}
        marks = {
            30: [row("2026-01-02", 3.0)] * 15 + [row("2026-07-02", 2.0)] * 10,
            60: [row("2026-01-02", 5.0)] * 15 + [row("2026-07-02", -1.0)] * 10,
            90: [row("2026-01-02", 1.0)] * 15 + [row("2026-07-02", 1.0)] * 10,
        }
        chosen = select_robust_hold(marks, date(2026, 7, 1))
        self.assertEqual(60, chosen["selected_hold_minutes"])
        self.assertFalse(chosen["holdout_passed"])

    def test_paid_exit_rule_selector_uses_training_only_then_checks_holdout(self) -> None:
        def row(day: str, pct: float) -> dict[str, object]:
            return {"signal_time": f"{day}T10:00:00", "return_pct": pct}
        marks = {
            rule: [row("2026-01-02", 1.0)] * 15 + [row("2026-03-03", 1.0)] * 10
            for rule in RULES
        }
        marks["vwap_loss_90m"] = [row("2026-01-02", 3.0)] * 15 + [row("2026-03-03", -1.0)] * 10
        chosen = select_training_rule(marks, date(2026, 3, 1))
        self.assertEqual("vwap_loss_90m", chosen["selected_exit_rule"])
        self.assertFalse(chosen["holdout_passed"])

    def test_one_minute_exit_waits_for_completed_confirmation(self) -> None:
        bars = tuple(
            _bar(index, 100 + index, 101 + index, 99 + index, 100 + index)
            for index in range(20)
        )
        signal = Signal("one_minute", Side.LONG, bars[14].timestamp, 114, 98, 130)
        entry = bars[15]
        plans = planned_one_minute_dynamic_exits(bars, signal, entry)
        self.assertIn("hybrid_stop_vwap_ema_90m", plans)
        self.assertGreaterEqual(plans["fixed_90m"].time, entry.timestamp)

    def test_one_minute_exit_names_non_default_cap_truthfully(self) -> None:
        bars = tuple(
            _bar(index, 100 + index, 101 + index, 99 + index, 100 + index)
            for index in range(20)
        )
        signal = Signal("one_minute", Side.LONG, bars[14].timestamp, 114, 98, 130)
        entry = bars[15]
        plans = planned_one_minute_dynamic_exits(bars, signal, entry, cap_minutes=60)
        self.assertIn("fixed_60m", plans)
        self.assertIn("structural_stop_60m", plans)
        self.assertEqual(entry.timestamp + timedelta(minutes=60), plans["fixed_60m"].time)

    def test_range_sweep_exit_waits_until_the_next_minute_after_vwap_touch(self) -> None:
        bars = tuple(
            _bar(index, 100, 101, 99, 100)
            for index in range(18)
        )
        signal = Signal("range_sweep", Side.LONG, bars[14].timestamp, 100, 98, 102)
        entry = bars[15]
        # The high reaches the live session VWAP on this completed minute.
        touch = Bar(bars[16].timestamp, 100, 102, 99, 101)
        plans = planned_range_sweep_reclaim_exits((*bars[:16], touch, *bars[17:]), signal, entry)
        self.assertEqual(touch.timestamp + timedelta(minutes=1), plans["vwap_touch_or_stop_60m"].time)
        self.assertEqual("vwap_touched", plans["vwap_touch_or_stop_60m"].reason)

    def test_range_sweep_exit_prefers_structural_stop_when_a_bar_hits_both_levels(self) -> None:
        bars = tuple(_bar(index, 100, 101, 99, 100) for index in range(18))
        signal = Signal("range_sweep", Side.LONG, bars[14].timestamp, 100, 98, 102)
        entry = bars[15]
        both = Bar(bars[16].timestamp, 100, 103, 97, 101)
        plans = planned_range_sweep_reclaim_exits((*bars[:16], both, *bars[17:]), signal, entry)
        self.assertEqual("structural_stop", plans["vwap_touch_or_stop_60m"].reason)

    def test_one_minute_exit_comparison_uses_same_signals_for_each_rule(self) -> None:
        rows = {
            "fixed_90m": [{"signal_time": "2026-01-01T10:00:00"}],
            "structural_stop_90m": [
                {"signal_time": "2026-01-01T10:00:00"}, {"signal_time": "2026-01-02T10:00:00"},
            ],
        }
        common = comparable_markouts(rows)
        self.assertEqual([{"signal_time": "2026-01-01T10:00:00"}], common["fixed_90m"])
        self.assertEqual([{"signal_time": "2026-01-01T10:00:00"}], common["structural_stop_90m"])

    def test_orb_pullback_adapter_does_not_emit_the_retired_delayed_candle_model(self) -> None:
        """The old five-minute evaluator cannot race the quote-level retouch path."""
        import pandas as pd
        from strategies.orb_pullback_v2 import evaluate

        self.assertIsNone(evaluate(pd.DataFrame({"time": pd.date_range("2026-01-02 09:30", periods=15, freq="5min")}), "TSLA"))

    def test_orb_pullback_adapter_locks_the_paid_selected_retest_tolerance(self) -> None:
        """Paper signals must use the paid study's 0.05% winner, not baseline 0.10%."""
        from strategies.orb_pullback_v2 import PAID_RETEST_TOLERANCE_PCT

        self.assertEqual(0.0005, PAID_RETEST_TOLERANCE_PCT)

    def test_orb_pullback_adapter_is_hard_scoped_to_paid_tsla_evidence(self) -> None:
        """A future pilot must not reuse the TSLA-only hypothesis on another ticker."""
        import pandas as pd
        from strategies.orb_pullback_v2 import evaluate

        frame = pd.DataFrame(columns=["time"])
        self.assertIsNone(evaluate(frame, "AAPL"))
        self.assertIsNone(evaluate(frame, "QQQ"))
        # TSLA reaches the normal data-availability check instead of being
        # rejected for its ticker.
        self.assertIsNone(evaluate(frame, "TSLA"))

    def test_incomplete_bot_state_is_treated_as_stopped_on_service_restart(self) -> None:
        from config import load_bot_state_safely
        with TemporaryDirectory() as directory:
            state_file = Path(directory) / "bot_state.json"
            state_file.write_text("")
            self.assertIsNone(load_bot_state_safely(state_file))
            state_file.write_text("{not json")
            self.assertIsNone(load_bot_state_safely(state_file))
            state_file.write_text('{"running": true}')
            self.assertEqual({"running": True}, load_bot_state_safely(state_file))

    def test_databento_cbbo_import_keeps_target_usable_occ_quotes(self) -> None:
        with TemporaryDirectory() as directory:
            source = Path(directory) / "opra.csv"
            output = Path(directory) / "normalized.csv"
            source.write_text(
                "ts_event,symbol,bid_px_00,ask_px_00\n"
                "2026-08-03T14:30:00Z,TSLA  260807C00300000,4.90,5.10\n"
                "2026-08-03T14:30:00Z,SPY   260807C00600000,3.90,4.10\n"
                "2026-08-03T14:31:00Z,TSLA  260807P00300000,0,2.10\n"
                "2026-08-03T14:32:00Z,TSLA  260807P00300000,5.20,5.40\n",
                encoding="utf-8",
            )
            normalize_databento_cbbo_files([source], "TSLA", output)
            quotes = load_option_quotes(output)

        self.assertEqual(2, len(quotes))
        self.assertEqual("TSLA", quotes[0].underlying)
        self.assertEqual("call", quotes[0].option_type)
        self.assertEqual(300.0, quotes[0].strike)
        self.assertEqual(4.9, quotes[0].bid)
        self.assertEqual("put", quotes[1].option_type)

    def test_databento_cbbo_import_honors_inclusive_date_window(self) -> None:
        with TemporaryDirectory() as directory:
            source = Path(directory) / "opra.csv"
            output = Path(directory) / "normalized.csv"
            source.write_text(
                "ts_event,symbol,bid_px_00,ask_px_00\n"
                "2026-06-30T14:30:00Z,TSLA  260703C00300000,2.00,2.10\n"
                "2026-07-01T14:30:00Z,TSLA  260703C00300000,2.10,2.20\n"
                "2026-07-02T14:30:00Z,TSLA  260703C00300000,2.20,2.30\n",
                encoding="utf-8",
            )
            normalize_databento_cbbo_files(
                [source], "TSLA", output, start_date=date(2026, 7, 1), end_date=date(2026, 7, 1),
            )
            quotes = load_option_quotes(output)

        self.assertEqual(1, len(quotes))
        self.assertEqual(date(2026, 7, 1), quotes[0].timestamp.date())

    def test_databento_cbbo_import_accepts_delivery_batch_ordering(self) -> None:
        with TemporaryDirectory() as directory:
            source = Path(directory) / "opra.csv"
            output = Path(directory) / "normalized.csv"
            source.write_text(
                "ts_recv,symbol,bid_px_00,ask_px_00\n"
                "2026-07-01T14:31:00Z,TSLA  260703C00300000,2.10,2.20\n"
                "2026-07-01T14:30:00Z,TSLA  260703P00300000,2.00,2.10\n",
                encoding="utf-8",
            )
            normalize_databento_cbbo_files([source], "TSLA", output)
            book = OptionQuoteBook(load_option_quotes(output))

        quote = book.first_quote_at_or_after(
            "TSLA  260703P00300000", datetime(2026, 7, 1, 14, 30, tzinfo=UTC),
        )
        self.assertIsNotNone(quote)
        self.assertEqual(2.1, quote.ask if quote else None)

    def test_option_quote_book_uses_future_ask_and_same_contract_bid(self) -> None:
        decision = datetime(2026, 8, 3, 10, 0)
        call = OptionQuote(
            datetime(2026, 8, 3, 10, 0, 30), "TSLA  260807C00300000", "TSLA",
            date(2026, 8, 7), 300.0, "call", 4.9, 5.1,
        )
        later_call = OptionQuote(
            datetime(2026, 8, 3, 10, 1), "TSLA  260807C00300000", "TSLA",
            date(2026, 8, 7), 300.0, "call", 5.4, 5.6,
        )
        wide_call = OptionQuote(
            datetime(2026, 8, 3, 10, 0, 30), "TSLA  260807C00305000", "TSLA",
            date(2026, 8, 7), 305.0, "call", 2.0, 3.0,
        )
        book = OptionQuoteBook((call, later_call, wide_call))

        selected = book.select_near_money("TSLA", "call", decision, 300.0)
        exit_quote = book.first_quote_at_or_after(call.option_symbol, datetime(2026, 8, 3, 10, 1))

        self.assertEqual(call, selected)
        self.assertEqual(5.1, selected.buy_fill())
        self.assertEqual(5.4, exit_quote.sell_fill() if exit_quote else None)

    def test_option_markout_uses_ask_then_same_contract_bid(self) -> None:
        bars = [_bar(index * 5, 100 + index, 101 + index, 99 + index, 100 + index) for index in range(15)]
        entry_time = bars[2].timestamp
        exit_time = entry_time + timedelta(minutes=60)
        quotes = OptionQuoteBook((
            OptionQuote(entry_time, "TSLA  260109C00102000", "TSLA", date(2026, 1, 9), 102, "call", 4.9, 5.1),
            OptionQuote(exit_time, "TSLA  260109C00102000", "TSLA", date(2026, 1, 9), 102, "call", 5.4, 5.6),
        ))

        results = run_option_markouts(bars, quotes, _OneLong(), underlying="TSLA")

        self.assertEqual(1, len(results))
        self.assertEqual(5.1, results[0].entry_ask)
        self.assertEqual(5.4, results[0].exit_bid)

    def test_streaming_databento_markout_uses_entry_ask_then_exit_bid(self) -> None:
        bars = [
            Bar(bar.timestamp.replace(tzinfo=UTC), bar.open, bar.high, bar.low, bar.close, bar.volume)
            for bar in [_bar(index * 5, 100 + index, 101 + index, 99 + index, 100 + index) for index in range(15)]
        ]
        entry_time = bars[2].timestamp
        exit_time = entry_time + timedelta(minutes=60)
        with TemporaryDirectory() as directory:
            source = Path(directory) / "opra.csv"
            source.write_text(
                "ts_recv,symbol,bid_px_00,ask_px_00\n"
                f"{entry_time.isoformat()},TSLA  260109C00103000,4.90,5.10\n"
                f"{entry_time.isoformat()},TSLA  260109C00100000,4.00,5.80\n"
                f"{exit_time.isoformat()},TSLA  260109C00103000,5.40,5.60\n",
                encoding="utf-8",
            )
            results = run_databento_cbbo_markouts(bars, [source], _OneLong(), underlying="TSLA")

        self.assertEqual(1, len(results))
        self.assertEqual(5.1, results[0].entry_ask)
        self.assertEqual(5.4, results[0].exit_bid)
        self.assertAlmostEqual(5.8824, results[0].return_pct, places=4)

    def test_multi_hold_stream_matches_three_single_hold_streams(self) -> None:
        bars = [
            Bar(bar.timestamp.replace(tzinfo=UTC), bar.open, bar.high, bar.low, bar.close, bar.volume)
            for bar in [_bar(index * 5, 100 + index, 101 + index, 99 + index, 100 + index) for index in range(25)]
        ]
        entry_time = bars[2].timestamp
        contract = "TSLA  260109C00103000"
        with TemporaryDirectory() as directory:
            source = Path(directory) / "opra.csv"
            source.write_text(
                "ts_recv,symbol,bid_px_00,ask_px_00\n"
                f"{entry_time.isoformat()},{contract},4.90,5.10\n"
                f"{(entry_time + timedelta(minutes=30)).isoformat()},{contract},5.00,5.20\n"
                f"{(entry_time + timedelta(minutes=60)).isoformat()},{contract},5.40,5.60\n"
                f"{(entry_time + timedelta(minutes=90)).isoformat()},{contract},5.80,6.00\n",
                encoding="utf-8",
            )
            multi = run_databento_cbbo_markouts_for_holds(
                bars, [source], _OneLong(), underlying="TSLA", hold_minutes=(30, 60, 90),
            )
            singles = {
                hold: run_databento_cbbo_markouts(
                    bars, [source], _OneLong(), underlying="TSLA", hold_minutes=hold,
                )
                for hold in (30, 60, 90)
            }
        self.assertEqual(singles, multi)

    def test_labeled_multi_hold_stream_matches_separate_labeled_scans(self) -> None:
        bars = [
            Bar(bar.timestamp.replace(tzinfo=UTC), bar.open, bar.high, bar.low, bar.close, bar.volume)
            for bar in [_bar(index * 5, 100 + index, 101 + index, 99 + index, 100 + index) for index in range(25)]
        ]
        entry_time = bars[2].timestamp
        contract = "TSLA  260109C00103000"
        signals = {"first": (Signal("FIRST", Side.LONG, bars[1].timestamp, 101, 98, 104, {}),),
                   "second": (Signal("SECOND", Side.LONG, bars[1].timestamp, 101, 98, 104, {}),)}
        with TemporaryDirectory() as directory:
            source = Path(directory) / "opra.csv"
            source.write_text(
                "ts_recv,symbol,bid_px_00,ask_px_00\n"
                f"{entry_time.isoformat()},{contract},4.90,5.10\n"
                f"{(entry_time + timedelta(minutes=30)).isoformat()},{contract},5.00,5.20\n"
                f"{(entry_time + timedelta(minutes=60)).isoformat()},{contract},5.40,5.60\n"
                f"{(entry_time + timedelta(minutes=90)).isoformat()},{contract},5.80,6.00\n",
                encoding="utf-8",
            )
            fast = run_databento_cbbo_markouts_for_labeled_signals_and_holds(
                bars, [source], signals, "TSLA", hold_minutes=(30, 60, 90),
            )
            separate = {
                label: {
                    hold: run_databento_cbbo_markouts_for_labeled_signals(
                        bars, [source], {label: rows}, "TSLA", hold_minutes=hold,
                    )[label]
                    for hold in (30, 60, 90)
                }
                for label, rows in signals.items()
            }
        self.assertEqual(separate, fast)

    def test_streaming_markout_returns_empty_result_for_no_signal_day(self) -> None:
        bars = [_bar(0, 100, 101, 99, 100)]
        # _OneLong emits only after two bars, so this is a normal quiet day.
        self.assertEqual(
            (),
            run_databento_cbbo_markouts(bars, [Path("unused.csv")], _OneLong(), underlying="TSLA", hold_minutes=90),
        )
        self.assertEqual(
            {30: (), 90: ()},
            run_databento_cbbo_markouts_for_holds(
                bars, [Path("unused.csv")], _OneLong(), underlying="TSLA", hold_minutes=(30, 90),
            ),
        )

    def test_vwap_and_ema_exit_plans_wait_for_completed_later_bar(self) -> None:
        bars = [
            Bar(datetime(2026, 1, 2, 9, 30), 100, 101, 99, 100, 100),
            Bar(datetime(2026, 1, 2, 9, 35), 100, 101, 99, 100, 100),
            Bar(datetime(2026, 1, 2, 9, 40), 101, 102, 100, 101, 100),
            Bar(datetime(2026, 1, 2, 9, 45), 99, 100, 98, 99, 100),
        ]
        signal = Signal("TEST", Side.LONG, bars[1].timestamp, 100, 98, 104, {})
        plans = planned_exits(bars, signal, bars[2], hold_minutes=90, ema_length=2)
        self.assertEqual(datetime(2026, 1, 2, 9, 50), plans["vwap_loss_90m"].time)
        self.assertEqual("vwap_loss", plans["vwap_loss_90m"].reason)
        self.assertEqual("ema9_loss", plans["ema9_loss_90m"].reason)

    def test_streaming_exit_plans_use_same_entry_contract_and_real_bid(self) -> None:
        bars = [
            Bar(bar.timestamp.replace(tzinfo=UTC), bar.open, bar.high, bar.low, bar.close, bar.volume)
            for bar in [_bar(index * 5, 100 + index, 101 + index, 99 + index, 100 + index) for index in range(25)]
        ]
        signal = _OneLong().evaluate(bars[:2])
        assert signal is not None
        entry_time = bars[2].timestamp
        plans = {label: {signal.timestamp: plan} for label, plan in planned_exits(bars, signal, bars[2]).items()}
        contract = "TSLA  260109C00103000"
        with TemporaryDirectory() as directory:
            source = Path(directory) / "opra.csv"
            source.write_text(
                "ts_recv,symbol,bid_px_00,ask_px_00\n"
                f"{entry_time.isoformat()},{contract},4.90,5.10\n"
                f"{(entry_time + timedelta(minutes=90)).isoformat()},{contract},5.40,5.60\n",
                encoding="utf-8",
            )
            results = run_databento_cbbo_markouts_for_exit_plans(
                bars, [source], _OneLong(), "TSLA", plans,
            )
        self.assertEqual(1, len(results["fixed_90m"]))
        self.assertEqual(contract, results["fixed_90m"][0].contract_symbol)
        self.assertEqual(5.4, results["fixed_90m"][0].exit_bid)

    def test_supertrend_emits_a_completed_bar_flip(self) -> None:
        bars = [_bar(i, 100 + i, 101 + i, 99 + i, 100 + i) for i in range(12)]
        bars.extend(_bar(12 + i, 111 - i * 3, 112 - i * 3, 110 - i * 3, 111 - i * 3) for i in range(8))
        signals = [SuperTrendReversal().evaluate(bars[:index]) for index in range(11, len(bars) + 1)]
        signal = next((item for item in signals if item is not None), None)
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(Side.SHORT, signal.side)

    def test_supertrend_reversal_closes_on_opposite_next_bar_open(self) -> None:
        bars = [_bar(i, 100 + i, 101 + i, 99 + i, 100 + i) for i in range(25)]
        bars.extend(_bar(25 + i, 124 - i * 3, 125 - i * 3, 123 - i * 3, 124 - i * 3) for i in range(12))
        trades = SuperTrendReversalSimulator(ReversalSimulationConfig(slippage_bps=0)).run(bars, SuperTrendReversal())
        self.assertGreaterEqual(len(trades), 1)
        self.assertIn(trades[0].exit_reason, {"opposite_flip", "end_of_data"})

    def test_signal_fills_next_bar_not_signal_bar(self) -> None:
        bars = [_bar(0, 100, 101, 99, 100), _bar(1, 100, 101, 99, 100),
                _bar(2, 102, 105, 101, 104), _bar(3, 104, 104, 103, 103)]
        trades = Simulator(SimulationConfig(slippage_bps=0)).run(bars, _OneLong())
        self.assertEqual(1, len(trades))
        self.assertEqual(102, trades[0].entry_price)
        self.assertEqual("target", trades[0].exit_reason)

    def test_stateful_strategy_receives_bars_while_position_is_open(self) -> None:
        bars = [_bar(0, 100, 101, 99, 100), _bar(1, 100, 101, 99, 100),
                _bar(2, 100, 101, 99, 100), _bar(3, 100, 101, 99, 100),
                _bar(4, 100, 101, 99, 100)]
        strategy = _TrackingStrategy()
        Simulator(SimulationConfig(slippage_bps=0, max_hold_bars=10)).run(bars, strategy)
        self.assertEqual([1, 2, 3, 4, 5], strategy.seen)

    def test_trailing_stop_only_applies_on_following_bar(self) -> None:
        bars = [_bar(0, 100, 101, 99, 100), _bar(1, 100, 101, 99, 100),
                _bar(2, 100, 101, 99, 100), _bar(3, 100, 103, 99, 102),
                _bar(4, 102, 103, 101, 102)]
        trades = Simulator(SimulationConfig(slippage_bps=0)).run(bars, _TrailingLong())
        self.assertEqual(1, len(trades))
        self.assertEqual(bars[4].timestamp, trades[0].exit_time)
        self.assertEqual("stop", trades[0].exit_reason)
        self.assertEqual(102, trades[0].exit_price)

    def test_ambiguous_bar_uses_stop_first(self) -> None:
        bars = [_bar(0, 100, 101, 99, 100), _bar(1, 100, 101, 99, 100),
                _bar(2, 100, 101, 99, 100), _bar(3, 100, 105, 97, 102)]
        trades = Simulator(SimulationConfig(slippage_bps=0)).run(bars, _OneLong())
        self.assertEqual("stop", trades[0].exit_reason)
        self.assertEqual(98, trades[0].exit_price)

    def test_intraday_simulator_flattens_at_configured_session_exit(self) -> None:
        bars = [
            Bar(datetime(2026, 1, 2, 15, 40), 100, 101, 99, 100),
            Bar(datetime(2026, 1, 2, 15, 45), 100, 101, 99, 100),
            Bar(datetime(2026, 1, 2, 15, 50), 100, 101, 99, 100),
            Bar(datetime(2026, 1, 2, 15, 55), 100, 101, 99, 100),
            Bar(datetime(2026, 1, 5, 9, 30), 90, 91, 89, 90),
        ]
        trades = Simulator(SimulationConfig(slippage_bps=0, session_exit_time=datetime(2026, 1, 2, 15, 55).time())).run(bars, _OneLong())
        self.assertEqual(1, len(trades))
        self.assertEqual("session", trades[0].exit_reason)
        self.assertEqual(bars[3].timestamp, trades[0].exit_time)

    def test_validation_refuses_too_few_trades(self) -> None:
        bars = [_bar(0, 100, 101, 99, 100), _bar(1, 100, 101, 99, 100),
                _bar(2, 102, 105, 101, 104), _bar(3, 104, 104, 103, 103)]
        trades = Simulator(SimulationConfig(slippage_bps=0)).run(bars, _OneLong())
        result = validate(trades, ValidationConfig(min_trades=2, max_drawdown_pct=10_000))
        self.assertFalse(result.passed)
        self.assertIn("only 1 trades; need 2", result.reasons)

    def test_csv_dataset_is_hashed_and_requires_chronology(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "bars.csv"
            path.write_text(
                "timestamp,open,high,low,close,volume\n"
                "2026-01-02T09:30:00+00:00,100,101,99,100,10\n"
                "2026-01-02T09:31:00+00:00,100,102,100,101,11\n",
                encoding="utf-8",
            )
            dataset = load_csv(path)
        self.assertEqual(2, len(dataset.bars))
        self.assertEqual(64, len(dataset.sha256))

    def test_option_quote_loader_uses_executable_bid_ask(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "quotes.csv"
            path.write_text("timestamp,option_symbol,underlying,expiration,strike,option_type,bid,ask,iv,delta,open_interest\n"
                            "2026-01-02T10:00:00-05:00,TSLA260109C00300000,TSLA,2026-01-09,300,call,4.90,5.10,0.42,0.51,100\n")
            quotes = load_option_quotes(path)
        self.assertEqual(5.10, quotes[0].buy_fill())
        self.assertEqual(4.90, quotes[0].sell_fill())

    def test_resample_regular_session_uses_complete_anchored_buckets(self) -> None:
        start = datetime(2026, 1, 2, 9, 30)
        bars = tuple(Bar(start + timedelta(minutes=5 * index), 100 + index,
                         101 + index, 99 + index, 100.5 + index, 10 + index)
                     for index in range(4))
        output = resample_regular_session(bars, 5, 15)
        self.assertEqual(1, len(output))
        self.assertEqual(start, output[0].timestamp)
        self.assertEqual(100, output[0].open)
        self.assertEqual(103, output[0].high)
        self.assertEqual(99, output[0].low)
        self.assertEqual(102.5, output[0].close)
        self.assertEqual(33, output[0].volume)

    def test_hold_study_uses_the_strategy_defining_candle_timeframe(self) -> None:
        """A 15-minute EMA formation must never be evaluated as a 1-minute one."""
        start = datetime(2026, 1, 2, 9, 30)
        bars = tuple(
            Bar(start + timedelta(minutes=index), 100, 101, 99, 100.5, 10)
            for index in range(30)
        )
        self.assertEqual(2, len(strategy_bars_for_hold_test("ema_pullback_rth", bars)))
        self.assertEqual(1, len(strategy_bars_for_hold_test("bollinger_keltner_squeeze_rth", bars)))
        self.assertEqual(6, len(strategy_bars_for_hold_test("trend_continuation", bars)))
        self.assertEqual(6, len(strategy_bars_for_hold_test("bollinger_w_bottom_rth", bars)))
        self.assertEqual(bars, strategy_bars_for_hold_test("turtle_soup_rth", bars))

    def test_ema_history_only_generates_signals_after_completed_15_minute_bar(self) -> None:
        # The helper is allowed to return no signals on synthetic data; this
        # checks its public shape and guards the completion-time contract.
        start = datetime(2026, 1, 2, 9, 30)
        bars = tuple(
            Bar(start + timedelta(minutes=index), 100, 101, 99, 100, 10)
            for index in range(30)
        )
        signals = ema_signals_by_completed_day(bars)
        for trading_day, values in signals.items():
            self.assertEqual(start.date(), trading_day)
            self.assertTrue(all(value.timestamp.minute % 15 == 0 for value in values))

    def test_squeeze_history_only_generates_signals_after_completed_30_minute_bar(self) -> None:
        start = datetime(2026, 1, 2, 9, 30)
        bars = tuple(
            Bar(start + timedelta(minutes=index), 100, 101, 99, 100, 10)
            for index in range(60)
        )
        signals = squeeze_signals_by_completed_day(bars)
        for trading_day, values in signals.items():
            self.assertEqual(start.date(), trading_day)
            self.assertTrue(all(value.timestamp.minute in {0, 30} for value in values))

    def test_squeeze_momentum_history_only_generates_signals_after_completed_30_minute_bar(self) -> None:
        start = datetime(2026, 1, 2, 9, 30)
        bars = tuple(
            Bar(start + timedelta(minutes=index), 100, 101, 99, 100, 10)
            for index in range(90)
        )
        signals = squeeze_signals_by_completed_day(bars, "squeeze_momentum_rth")
        for trading_day, values in signals.items():
            self.assertEqual(start.date(), trading_day)
            self.assertTrue(all(value.timestamp.minute in {0, 30} for value in values))

    def test_squeeze_momentum_rejects_an_unreleased_compression(self) -> None:
        strategy = SqueezeMomentumRTH(SqueezeMomentumRTHConfig(length=5, min_squeeze_bars=2))
        start = datetime(2026, 1, 2, 9, 30)
        bars = tuple(
            Bar(start + timedelta(minutes=30 * index), 100, 100.05, 99.95, 100 + (index % 2) * .01, 1)
            for index in range(12)
        )
        self.assertTrue(all(strategy.evaluate(bars[:index + 1]) is None for index in range(len(bars))))

    def test_bollinger_w_bottom_requires_every_completed_confirmation_stage(self) -> None:
        config = BollingerWBottomRTHConfig(
            length=5, entry_start=time(9, 30), entry_end=time(15, 0),
            reaction_limit_bars=3, second_low_limit_bars=3, confirmation_limit_bars=3,
        )
        strategy = BollingerWBottomRTH(config)
        start = datetime(2026, 1, 2, 9, 30)
        # Five quiet bars warm the bands; then a first lower-band reaction,
        # middle-band rebound, lower-but-in-band retest, and resistance close.
        bars = tuple(
            Bar(start + timedelta(minutes=5 * index), 100, 101, 99, 100 + (index % 2) * .2, 1)
            for index in range(5)
        ) + (
            Bar(start + timedelta(minutes=25), 100, 100.2, 94, 95, 1),
            Bar(start + timedelta(minutes=30), 95, 101, 95, 100.8, 1),
            Bar(start + timedelta(minutes=35), 100.8, 101, 94.5, 96, 1),
            Bar(start + timedelta(minutes=40), 96, 102, 96, 101.5, 1),
        )
        signals = []
        for index in range(len(bars)):
            signal = strategy.evaluate(bars[:index + 1])
            if signal:
                signals.append(signal)
        self.assertEqual(1, len(signals))
        self.assertEqual(Side.LONG, signals[0].side)
        self.assertEqual("confirmed_bollinger_w_bottom", signals[0].features["trigger"])

    def test_bollinger_w_bottom_quote_fill_waits_until_after_confirmation_candle(self) -> None:
        """A five-minute confirmation labelled 10:10 must not fill at 10:10."""
        start = datetime(2026, 1, 2, 9, 30)
        dataset_bars = tuple(
            Bar(start + timedelta(minutes=5 * index), 100, 101, 99, 100 + (index % 2) * .2, 1)
            for index in range(5)
        ) + (
            Bar(start + timedelta(minutes=25), 100, 100.2, 94, 95, 1),
            Bar(start + timedelta(minutes=30), 95, 101, 95, 100.8, 1),
            Bar(start + timedelta(minutes=35), 100.8, 101, 94.5, 96, 1),
            Bar(start + timedelta(minutes=40), 96, 102, 96, 101.5, 1),
        )
        # The production configuration needs 20 bars, but the timing helper
        # is exercised here with its own deterministic, minimal construction.
        strategy = BollingerWBottomRTH(BollingerWBottomRTHConfig(
            length=5, entry_start=time(9, 30), entry_end=time(15, 0),
            reaction_limit_bars=3, second_low_limit_bars=3, confirmation_limit_bars=3,
        ))
        raw = strategy_signals(dataset_bars, strategy)
        self.assertEqual(1, len(raw))
        self.assertEqual(start + timedelta(minutes=40), raw[0].timestamp)

        completed = bollinger_w_bottom_signals_by_completed_day(
            dataset_bars,
            source=BollingerWBottomRTH(BollingerWBottomRTHConfig(
                length=5, entry_start=time(9, 30), entry_end=time(15, 0),
                reaction_limit_bars=3, second_low_limit_bars=3, confirmation_limit_bars=3,
            )),
        )
        self.assertEqual(1, len(completed[start.date()]))
        self.assertEqual(start + timedelta(minutes=45), completed[start.date()][0].timestamp)

    def test_bollinger_keltner_squeeze_requires_a_completed_range_break(self) -> None:
        config = BollingerKeltnerSqueezeRTHConfig(
            length=5, min_squeeze_bars=2, entry_start=time(9, 30), entry_end=time(15, 0),
        )
        strategy = BollingerKeltnerSqueezeRTH(config)
        start = datetime(2026, 1, 2, 9, 30)
        bars = (
            Bar(start, 100, 105, 95, 100, 1),
            Bar(start + timedelta(minutes=30), 100, 105, 95, 100.1, 1),
            Bar(start + timedelta(minutes=60), 100.1, 106, 99, 100.0, 1),
            Bar(start + timedelta(minutes=90), 100.0, 105, 95, 100.1, 1),
            Bar(start + timedelta(minutes=120), 100.1, 106, 99, 100.0, 1),
            Bar(start + timedelta(minutes=150), 100.0, 106, 99, 100.1, 1),
            Bar(start + timedelta(minutes=180), 100.1, 132, 99, 130, 1),
        )
        signals = []
        for index in range(len(bars)):
            signal = strategy.evaluate(bars[:index + 1])
            if signal:
                signals.append(signal)
        self.assertEqual(1, len(signals))
        self.assertEqual(Side.LONG, signals[0].side)
        self.assertEqual("upward_release_after_compression", signals[0].features["trigger"])

    def test_trend_continuation_emits_only_fresh_breakout(self) -> None:
        bars = []
        for minute in range(21):
            price = 100 + minute * 0.2
            bars.append(_bar(minute, price, price + 0.1, price - 0.1, price))
        bars[-1] = _bar(20, 104.0, 105.0, 103.9, 104.9)
        strategy = TrendContinuation(TrendContinuationConfig(fast_ema=3, slow_ema=6, breakout_bars=3, atr_bars=3))
        signal = strategy.evaluate(bars)
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(Side.LONG, signal.side)
        self.assertGreater(signal.target, signal.entry_reference)

    def test_trend_breakout_episode_guard_waits_for_a_return_through_level(self) -> None:
        start = datetime(2026, 1, 2, 10, 0)
        bars = (
            Bar(start, 100, 101, 99, 100.5),
            Bar(start + timedelta(minutes=5), 101, 102, 100, 101.5),
            Bar(start + timedelta(minutes=10), 101.5, 101.6, 99.8, 100.0),
            Bar(start + timedelta(minutes=15), 100.0, 103, 99.9, 102.5),
        )
        def signal(index, side, level):
            entry = bars[index].close
            return Signal(
                "V2_TREND_CONT", side, bars[index].timestamp, entry,
                entry - 1 if side is Side.LONG else entry + 1,
                entry + 2 if side is Side.LONG else entry - 2,
                {"prior_high" if side is Side.LONG else "prior_low": level},
            )
        # Two long flags above the same breakout level are one setup.  Once
        # close returns through 101, a later long flag becomes a new attempt.
        signals = (signal(0, Side.LONG, 101), signal(1, Side.LONG, 101), signal(3, Side.LONG, 101))
        kept = _distinct_breakout_episodes(bars, signals)
        self.assertEqual((signals[0], signals[2]), kept)

    def test_spy_trend_research_signals_are_visible_only_after_five_minute_close(self) -> None:
        # The exact formation is not relevant here: patching the strategy
        # generator is avoided so this test simply asserts every returned
        # research signal carries the five-minute completion timestamp.
        bars = tuple(
            Bar(datetime(2026, 1, 2, 9, 30) + timedelta(minutes=index),
                100 + index * .1, 100.2 + index * .1, 99.9 + index * .1,
                100.1 + index * .1)
            for index in range(130)
        )
        signals = _completed_five_minute_signals(bars, "trend_continuation")
        for values in signals.values():
            self.assertTrue(all(value.timestamp.minute % 5 == 0 for value in values))

    def test_walk_forward_requires_both_segments_to_pass(self) -> None:
        bars = [_bar(i, 100, 101, 99, 100) for i in range(8)]
        result = run_walk_forward(
            bars, bars[4].timestamp, _OneLong,
            Simulator(SimulationConfig(slippage_bps=0)),
            ValidationConfig(min_trades=1, max_drawdown_pct=10_000),
        )
        self.assertFalse(result.promoted)
        self.assertEqual(1, result.train_validation.trade_count)
        self.assertEqual(1, result.holdout_validation.trade_count)
        self.assertFalse(result.holdout_validation.passed)

    def test_alpaca_export_filters_explicit_dates(self) -> None:
        class _Client:
            def get_bars(self, symbol, timeframe, limit):
                self.called = (symbol, timeframe, limit)
                return ([
                    {"t": "2026-07-14T13:30:00Z", "o": 100, "h": 101, "l": 99, "c": 100, "v": 4},
                    {"t": "2026-07-15T13:30:00Z", "o": 101, "h": 102, "l": 100, "c": 101, "v": 5},
                    {"t": "2026-07-15T19:55:00Z", "o": 102, "h": 103, "l": 101, "c": 102, "v": 6},
                ], False)
        with TemporaryDirectory() as directory:
            path = export_alpaca_csv(
                _Client(), "spy", datetime(2026, 7, 15).date(), datetime(2026, 7, 16).date(),
                Path(directory) / "bars.csv", limit=99,
            )
            dataset = load_csv(path)
        self.assertEqual(2, len(dataset.bars))
        self.assertEqual(101, dataset.bars[0].close)

    def test_alpaca_export_uses_requested_dates_and_pagination(self) -> None:
        class _Client:
            data = "https://example.test"

            def __init__(self):
                self.requests = []

            def _get(self, url, params):
                self.requests.append((url, params))
                if "page_token" not in params:
                    return {"bars": [{"t": "2026-07-15T13:30:00Z", "o": 100, "h": 101,
                                      "l": 99, "c": 100, "v": 4}], "next_page_token": "page-2"}
                return {"bars": [{"t": "2026-07-15T13:35:00Z", "o": 101, "h": 102,
                                  "l": 100, "c": 101, "v": 5}]}

        client = _Client()
        with TemporaryDirectory() as directory:
            path = export_alpaca_csv(
                client, "SPY", datetime(2026, 7, 15).date(), datetime(2026, 7, 16).date(),
                Path(directory) / "bars.csv", drop_partial_final_session=False,
            )
            dataset = load_csv(path)
        self.assertEqual(2, len(dataset.bars))
        self.assertEqual("2026-07-15T00:00:00-04:00", client.requests[0][1]["start"])
        self.assertEqual("page-2", client.requests[1][1]["page_token"])

    def test_alpaca_export_chunks_long_intervals_without_duplicates(self) -> None:
        class _Client:
            data = "https://example.test"

            def __init__(self):
                self.starts = []

            def _get(self, url, params):
                self.starts.append(params["start"][:10])
                if params["start"].startswith("2026-01-01"):
                    return {"bars": [{"t": "2026-01-02T14:30:00Z", "o": 100, "h": 101,
                                      "l": 99, "c": 100, "v": 1}]}
                return {"bars": [{"t": "2026-01-03T14:30:00Z", "o": 101, "h": 102,
                                  "l": 100, "c": 101, "v": 1}]}

        client = _Client()
        with TemporaryDirectory() as directory:
            path = export_alpaca_csv(
                client, "SPY", datetime(2026, 1, 1).date(), datetime(2026, 1, 4).date(),
                Path(directory) / "bars.csv", chunk_days=2, drop_partial_final_session=False,
            )
            dataset = load_csv(path)
        self.assertEqual(["2026-01-01", "2026-01-03"], client.starts)
        self.assertEqual(2, len(dataset.bars))

    def test_reconciliation_matches_side_and_entry_time_only_once(self) -> None:
        timestamp = datetime(2026, 1, 2, 10, 0)
        simulated = [Trade("TEST", Side.LONG, timestamp, timestamp, timestamp, 100, 101, 1,
                           1, 1, 0, 1, "target", {})]
        reference = [
            ReferenceTrade(Side.LONG, timestamp, timestamp, 100.1, 101),
            ReferenceTrade(Side.LONG, timestamp, timestamp, 100.1, 101),
        ]
        result = reconcile(reference, simulated)
        self.assertEqual(1, result.matched_count)
        self.assertEqual(1, result.unmatched_reference)
        self.assertEqual(0, result.unmatched_simulated)

    def test_trade_ledger_round_trips_immutable_trade_fields(self) -> None:
        timestamp = datetime(2026, 1, 2, 10, 0)
        original = Trade("TEST", Side.LONG, timestamp, timestamp, timestamp, 100, 101, 1,
                         1, 1, 0, 1, "target", {"setup": "test"})
        with TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.json"
            write_trade_ledger(path, [original])
            restored = load_trade_ledger(path)
        self.assertEqual((original,), restored)

    def test_alpaca_export_drops_premarket_and_partial_final_session(self) -> None:
        class _Client:
            def get_bars(self, symbol, timeframe, limit):
                return ([
                    {"t": "2026-07-15T12:00:00Z", "o": 90, "h": 91, "l": 89, "c": 90, "v": 1},
                    {"t": "2026-07-15T19:55:00Z", "o": 100, "h": 101, "l": 99, "c": 100, "v": 2},
                    {"t": "2026-07-16T13:30:00Z", "o": 101, "h": 102, "l": 100, "c": 101, "v": 3},
                ], False)
        with TemporaryDirectory() as directory:
            path = export_alpaca_csv(
                _Client(), "SPY", datetime(2026, 7, 15).date(), datetime(2026, 7, 17).date(),
                Path(directory) / "bars.csv",
            )
            dataset = load_csv(path)
        self.assertEqual(1, len(dataset.bars))
        self.assertEqual(datetime(2026, 7, 15, 15, 55, tzinfo=dataset.bars[0].timestamp.tzinfo), dataset.bars[0].timestamp)

    def test_alpaca_one_minute_export_requires_final_one_minute_bar(self) -> None:
        class _Client:
            def get_bars(self, symbol, timeframe, limit):
                return ([
                    {"t": "2026-07-15T19:59:00Z", "o": 100, "h": 101, "l": 99, "c": 100, "v": 2},
                    {"t": "2026-07-16T13:30:00Z", "o": 101, "h": 102, "l": 100, "c": 101, "v": 3},
                ], False)
        with TemporaryDirectory() as directory:
            path = export_alpaca_csv(
                _Client(), "SPY", date(2026, 7, 15), date(2026, 7, 17),
                Path(directory) / "bars.csv", timeframe="1Min",
            )
            dataset = load_csv(path)
        self.assertEqual(1, len(dataset.bars))
        self.assertEqual(time(15, 59), dataset.bars[0].timestamp.time())

    def test_vwap_pullback_requires_touch_then_reclaim(self) -> None:
        bars = []
        for minute in range(25):
            price = 100 + minute * 0.1
            bars.append(_bar(minute, price, price + 0.08, price - 0.08, price))
        # A deliberate VWAP touch followed by close back above it.
        bars[-2] = _bar(23, 102.2, 102.25, 101.1, 102.1)
        bars[-1] = _bar(24, 102.2, 102.7, 102.1, 102.6)
        signal = VWAPPullback(VWAPPullbackConfig(fast_ema=3, slow_ema=6, atr_bars=3, slope_bars=3)).evaluate(bars)
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(Side.LONG, signal.side)

    def test_two_leg_trend_pullback_requires_vwap_protected_reclaim(self) -> None:
        strategy = TwoLegTrendPullback(TwoLegTrendPullbackConfig(
            fast_ema=3, slow_ema=6, atr_bars=3, impulse_atr=.5,
            pullback_min_atr=.15, pullback_max_atr=3.0, entry_start=time(9, 55), entry_end=time(11, 30),
        ))
        bars = []
        for minute in range(25):
            close = 100 + minute * .08
            bars.append(_bar(minute, close - .03, close + .08, close - .08, close))
            self.assertIsNone(strategy.evaluate(bars))
        # First leg is established, then a controlled dip holds above VWAP.
        for minute, close in enumerate((101.35, 101.62, 101.92, 101.66, 101.72, 102.02, 101.80, 102.30), start=25):
            bars.append(_bar(minute, close - .04, close + .10, close - .18, close))
            result = strategy.evaluate(bars)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(Side.LONG, result.side)
        self.assertEqual("impulse_vwap_hold_pullback_1m_reclaim", result.features["trigger"])

    def test_two_leg_trend_pullback_cancels_when_pullback_loses_vwap(self) -> None:
        strategy = TwoLegTrendPullback(TwoLegTrendPullbackConfig(
            fast_ema=3, slow_ema=6, atr_bars=3, impulse_atr=.5,
            pullback_min_atr=.15, pullback_max_atr=3.0, entry_start=time(9, 55), entry_end=time(11, 30),
        ))
        bars = []
        for minute in range(25):
            close = 100 + minute * .08
            bars.append(_bar(minute, close - .03, close + .08, close - .08, close))
            strategy.evaluate(bars)
        # A valid first leg is present, but the pullback closes through VWAP.
        for minute, close in enumerate((101.35, 101.62, 101.92, 101.66, 101.72, 100.80), start=25):
            bars.append(_bar(minute, close - .04, close + .08, close - .25, close))
            self.assertIsNone(strategy.evaluate(bars))
        self.assertIsNone(strategy._state)

    def test_vwap_mean_reversion_requires_stretch_then_one_minute_reversal(self) -> None:
        strategy = VWAPMeanReversion(VWAPMeanReversionConfig(
            atr_bars=3, rsi_bars=3, stretch_atr=.5, oversold_rsi=49,
            overbought_rsi=51, stop_atr=.20, minimum_reward_risk=.15,
        ))
        bars = []
        # First create enough calm intraday history and an ordinary red bar;
        # it must not fire without a genuine extension below VWAP.
        for minute, close in enumerate((100, 100.1, 100.2, 100.1, 100.15, 100.1, 100.05, 100.0,
                                        99.95, 99.9, 99.85, 99.8, 99.75, 99.7, 99.65, 99.6,
                                        99.55, 99.5, 99.45, 99.4, 99.35, 99.3, 99.25, 99.2,
                                        99.15, 99.1, 99.05, 99.0, 98.95, 98.9, 98.85)):
            bars.append(_bar(minute, close + .04, close + .08, close - .08, close))
            self.assertIsNone(strategy.evaluate(bars))
        # A bullish completed candle after the prior stretched red bar is the
        # first moment a long may exist.  Fill would still be the *next* bar.
        bars.append(_bar(31, 98.82, 99.2, 98.8, 99.15))
        signal = strategy.evaluate(bars)
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(Side.LONG, signal.side)
        self.assertEqual("oversold_stretch_then_1m_reversal", signal.features["trigger"])

    def test_gap_zscore_context_uses_only_prior_completed_sessions(self) -> None:
        bars = []
        # Seven tiny synthetic sessions establish five prior gap observations.
        # The large final opening must affect only its own context, never an
        # earlier one (the causal property this strategy relies on).
        for offset in range(7):
            day = date(2026, 2, 2) + timedelta(days=offset)
            prior_close = 100 + offset
            opening = prior_close + (4 if offset == 6 else .10 * (offset % 2))
            bars.extend((
                Bar(datetime.combine(day, time(9, 30)), opening, opening + .1, opening - .1, opening),
                Bar(datetime.combine(day, time(15, 59)), prior_close + .2, prior_close + .3, prior_close, prior_close + .2),
            ))
        contexts = build_gap_zscore_contexts(bars, gap_window=5, regime_days=5)
        self.assertEqual(1, len(contexts))
        context = next(iter(contexts.values()))
        self.assertGreater(context.gap_zscore, 1)

    def test_gap_zscore_reversion_needs_range_and_vwap_reclaim(self) -> None:
        day = date(2026, 2, 9)
        context = {day: __import__('research.engine.strategies', fromlist=['GapZScoreContext']).GapZScoreContext(
            prior_close=102.0, gap_zscore=-1.5, daily_efficiency=.20,
        )}
        strategy = GapZScoreOpeningReversion(context, GapZScoreOpeningReversionConfig(
            atr_bars=3, minimum_gap_fill_room_atr=.1, entry_start=time(9, 46), entry_end=time(11, 0),
        ))
        bars = []
        for minute in range(15):
            close = 98.5 + (minute % 3) * .05
            bars.append(Bar(datetime.combine(day, time(9, 30)) + timedelta(minutes=minute), close, close + .1, close - .1, close))
            self.assertIsNone(strategy.evaluate(bars))
        # A completed 09:46 reclaim of the 15-minute range and VWAP is the
        # first point a signal can exist; a fill would still occur next bar.
        bars.append(Bar(datetime.combine(day, time(9, 45)), 98.6, 99.8, 98.5, 99.7))
        self.assertIsNone(strategy.evaluate(bars))
        bars.append(Bar(datetime.combine(day, time(9, 46)), 99.7, 100.2, 99.6, 100.1))
        signal = strategy.evaluate(bars)
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(Side.LONG, signal.side)
        self.assertEqual("negative_opening_gap_zscore_range_vwap_reclaim", signal.features["trigger"])

    def test_paid_vwap_study_counts_one_entry_until_price_revisits_vwap(self) -> None:
        # Two consecutive long reclaim signals are one pullback episode.  A
        # later move back through VWAP re-arms the strategy for a new setup.
        bars = tuple(_bar(index, 100, max(103, close + 1), 98, close)
                     for index, close in enumerate((100, 101, 102, 99, 101)))
        def signal(index):
            bar = bars[index]
            return Signal("V2_VWAP_PULLBACK", Side.LONG, bar.timestamp, bar.close,
                          bar.close - 1, bar.close + 2, {})
        kept = _distinct_touch_episodes(bars, (signal(1), signal(2), signal(4)))
        self.assertEqual((bars[1].timestamp, bars[4].timestamp), tuple(item.timestamp for item in kept))

    def test_ema_pullback_requires_prior_pullback_and_fresh_recross(self) -> None:
        config = EMAPullbackRTHConfig(pullback_ema=3, pullback_limit_ema=6, trend_ema=12,
                                      minimum_risk_pct=0.001)
        strategy = EMAPullbackRTH(config)
        bars = []
        for minute in range(30):
            price = 100 + minute * 0.4
            bars.append(_bar(minute, price, price + 0.2, price - 0.2, price))
            strategy.evaluate(bars)
        # Pull below the fast/limit EMA, then reclaim it in the established trend.
        signal = None
        for price in [109.0, 108.8, 109.8, 111.3]:
            minute = len(bars)
            bars.append(_bar(minute, price, price + 0.2, price - 0.35, price))
            candidate = strategy.evaluate(bars)
            if candidate is not None:
                signal = candidate
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(Side.LONG, signal.side)
        self.assertLess(signal.stop, signal.entry_reference)

    def test_turtle_soup_requires_next_bar_confirmation_after_sweep(self) -> None:
        strategy = TurtleSoupRTH(TurtleSoupRTHConfig(lookback_bars=5, entry_start=datetime(2026, 1, 2, 9, 30).time()))
        bars = []
        for minute in range(5):
            price = 100 + minute * 0.1
            bars.append(_bar(minute, price, price + 0.2, price - 0.2, price))
            self.assertIsNone(strategy.evaluate(bars))
        # Sweep prior lows; no same-bar reversal entry is allowed.
        bars.append(_bar(5, 100, 100.5, 98.5, 99.7))
        self.assertIsNone(strategy.evaluate(bars))
        # The next bar must reclaim the prior low.  It does not need to close
        # above the entire sweep candle, which would be a different setup.
        bars.append(_bar(6, 99.0, 100.2, 98.8, 100.0))
        signal = strategy.evaluate(bars)
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(Side.LONG, signal.side)
        self.assertEqual(98.5, signal.stop)

    def test_turtle_soup_requires_reclaim_of_prior_level_for_each_side(self) -> None:
        config = TurtleSoupRTHConfig(lookback_bars=5, entry_start=datetime(2026, 1, 2, 9, 30).time())
        strategy = TurtleSoupRTH(config)
        bars = []
        for minute in range(5):
            price = 100 - minute * 0.1
            bars.append(_bar(minute, price, price + .2, price - .2, price))
            self.assertIsNone(strategy.evaluate(bars))
        # An upside sweep that stays above the old high is not a reversal.
        bars.append(_bar(5, 100, 102, 99.8, 101.5))
        self.assertIsNone(strategy.evaluate(bars))
        bars.append(_bar(6, 101.5, 101.7, 100.1, 100.5))
        self.assertIsNone(strategy.evaluate(bars))
        # A new sweep followed by a reclaim below the prior high is a short.
        bars.append(_bar(7, 100.5, 102.3, 100.1, 101.8))
        self.assertIsNone(strategy.evaluate(bars))
        bars.append(_bar(8, 101.8, 102.0, 99.9, 100.0))
        signal = strategy.evaluate(bars)
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(Side.SHORT, signal.side)
        self.assertEqual(102.3, signal.stop)

    def test_gap_fill_requires_gap_cross_and_reclaim(self) -> None:
        strategy = GapFillRTH(GapFillRTHConfig(min_gap_pct=0.002, atr_bars=2, entry_start=datetime(2026, 1, 2, 9, 30).time()))
        day_one = [Bar(datetime(2026, 1, 1, 15, 50), 100, 101, 99, 100),
                   Bar(datetime(2026, 1, 1, 15, 55), 100, 101, 99, 100)]
        day_two = [Bar(datetime(2026, 1, 2, 9, 30), 101, 101.5, 100.5, 101),
                   Bar(datetime(2026, 1, 2, 9, 35), 100.8, 101.2, 99.5, 100.6)]
        self.assertIsNone(strategy.evaluate(day_one[:1]))
        self.assertIsNone(strategy.evaluate(day_one))
        self.assertIsNone(strategy.evaluate(day_one + day_two[:1]))
        signal = strategy.evaluate(day_one + day_two)
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(Side.LONG, signal.side)
        self.assertTrue(signal.features["no_profit_target"])
        # Staying above the reclaimed level must not create duplicate entries
        # from the same overnight gap.
        self.assertIsNone(strategy.evaluate(day_one + day_two + [
            Bar(datetime(2026, 1, 2, 9, 40), 100.6, 101.2, 100.4, 100.9)
        ]))

    def test_opening_momentum_emits_once_at_opening_window_close(self) -> None:
        strategy = OpeningMomentumRTH(OpeningMomentumRTHConfig(opening_bars=3, min_move_pct=.001, atr_bars=2))
        bars = [Bar(datetime(2026,1,1,15,50),100,101,99,100), Bar(datetime(2026,1,1,15,55),100,101,99,100),
                Bar(datetime(2026,1,2,9,30),100,101,99,100), Bar(datetime(2026,1,2,9,35),100,101,99,100.4), Bar(datetime(2026,1,2,9,40),100.4,101,100.3,100.8)]
        for index in range(4): self.assertIsNone(strategy.evaluate(bars[:index+1]))
        signal = strategy.evaluate(bars)
        self.assertIsNotNone(signal); assert signal is not None
        self.assertEqual(Side.LONG, signal.side)

    def test_regime_selection_uses_train_only_and_preserves_side(self) -> None:
        start = datetime(2026, 1, 2, 9, 30)
        bars = tuple(Bar(start + timedelta(minutes=5 * index), 100 + index, 101 + index,
                         99 + index, 100 + index, 1) for index in range(61))
        def trade(index, side, pnl):
            point = bars[index].timestamp
            return Trade("TEST", side, point, point, point, 100, 101, 1, pnl, pnl, 0, 0, "test", {})
        # Train has 30 trend-up long winners and 30 losing short trades; only
        # the observed long regime/side may be selected.
        train = [trade(index, Side.LONG, 2) for index in range(21, 51)]
        train += [trade(index, Side.SHORT, -2) for index in range(21, 51)]
        holdout = [trade(index, Side.LONG, 2) for index in range(21, 51)]
        result = select_regimes(train, holdout, bars, bars, ValidationConfig(min_trades=30, max_drawdown_pct=10000))
        self.assertEqual(("TREND_UP:LONG",), result.selected_keys)
        self.assertEqual(30, result.holdout_selected.trade_count)

    def test_paid_regime_context_selects_earlier_data_without_reselecting_later(self) -> None:
        cutoff = date(2026, 2, 1)
        def row(day, value):
            return {"signal_time": f"{day}T10:00:00", "return_pct": value}
        # All signals have a positive but smaller median in earlier data.
        # Choppy wins earlier, then fails later; it must remain selected rather
        # than being swapped for the baseline after the final-exam result.
        labeled = {
            "all_signals": [row("2026-01-02", 1)] * 30 + [row("2026-02-02", 1)] * 10,
            "trend_aligned": [row("2026-01-02", 2)] * 30 + [row("2026-02-02", 2)] * 10,
            "choppy": [row("2026-01-02", 3)] * 30 + [row("2026-02-02", -3)] * 10,
        }
        result = select_context(labeled, cutoff)
        self.assertEqual("choppy", result["selected_context"])
        self.assertFalse(result["later_passed"])
        self.assertEqual("reject", result["decision"])

    def test_afternoon_reversal_requires_confirmed_structure_and_break(self) -> None:
        bars = []
        start = datetime(2026, 1, 2, 9, 30)
        prices = [100, 99.7, 99.4, 99.1, 99.5, 100.0, 100.4, 100.1, 99.8, 99.5,
                  99.8, 100.1, 100.5, 100.2, 99.9, 100.2, 100.5, 100.9, 101.2]
        for index, price in enumerate(prices):
            bars.append(Bar(start + timedelta(minutes=index * 15), price, price + 0.08,
                            price - 0.08, price, 100))
        # Last close breaks the confirmed 10:45 swing high after the higher 12:00 low.
        strategy = AfternoonReversal(AfternoonReversalConfig(pivot_lookback=1, atr_bars=3))
        signal = strategy.evaluate(bars)
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(Side.LONG, signal.side)

    def test_fair_value_gap_requires_first_retest_and_reclaim(self) -> None:
        bars = []
        for minute in range(24):
            price = 100 + minute * 0.1
            bars.append(_bar(minute, price, price + 0.05, price - 0.05, price))
        # Bar 19 creates an upward FVG with bar 21; current bar is first retest.
        bars[18] = _bar(18, 101.8, 101.85, 101.75, 101.8)
        bars[19] = _bar(19, 101.8, 102.5, 101.8, 102.4)
        bars[20] = _bar(20, 102.3, 102.45, 102.1, 102.3)
        bars[21] = _bar(21, 102.3, 102.5, 102.15, 102.3)
        bars[22] = _bar(22, 102.3, 102.5, 102.15, 102.4)
        bars[23] = _bar(23, 102.4, 102.5, 101.95, 102.25)
        signal = FairValueGap(FairValueGapConfig(fast_ema=3, slow_ema=6, atr_bars=3, scan_bars=8)).evaluate(bars)
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(Side.LONG, signal.side)

    def test_orb_pullback_requires_breakout_retest_then_bounce(self) -> None:
        bars = [
            _bar(0, 100.0, 100.2, 99.8, 100.0),
            _bar(5, 100.0, 100.3, 99.9, 100.1),
            _bar(10, 100.1, 100.4, 99.9, 100.2),
            _bar(15, 100.3, 100.8, 100.3, 100.7),  # breakout
            _bar(20, 100.6, 100.6, 100.35, 100.45),  # first retest
            _bar(25, 100.45, 100.85, 100.4, 100.8),  # confirmed bounce
        ]
        signal = OpeningRangePullback(OpeningRangePullbackConfig(atr_bars=3)).evaluate(bars)
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(Side.LONG, signal.side)
        self.assertEqual(100.35, signal.stop)

    def test_confirmed_orb_requires_range_and_vwap_aligned_close(self) -> None:
        bars = [
            _bar(0, 100.0, 100.2, 99.8, 100.0), _bar(5, 100.0, 100.3, 99.9, 100.2),
            _bar(10, 100.2, 100.4, 100.0, 100.3), _bar(15, 100.4, 100.8, 100.4, 100.7),
        ]
        signal = OpeningRangeBreakout(OpeningRangeBreakoutConfig(min_range_pct=0.001)).evaluate(bars)
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(Side.LONG, signal.side)

    def test_confirmed_orb_can_limit_direction(self) -> None:
        bars = [
            _bar(0, 100.0, 100.2, 99.8, 100.0), _bar(5, 100.0, 100.3, 99.9, 100.2),
            _bar(10, 100.2, 100.4, 100.0, 100.3), _bar(15, 100.4, 100.8, 100.4, 100.7),
        ]
        signal = OpeningRangeBreakout(OpeningRangeBreakoutConfig(
            min_range_pct=0.001, allow_long=False,
        )).evaluate(bars)
        self.assertIsNone(signal)

    def test_orb_rsi_macd_requires_prior_indicator_history(self) -> None:
        from research.engine.strategies import ORBRsiMacdShort
        bars = [_bar(index * 5, 100 - index * .03, 100.03 - index * .03,
                     99.97 - index * .03, 100 - index * .03) for index in range(30)]
        self.assertIsNone(ORBRsiMacdShort().evaluate(bars[:4]))

    def test_orb_rsi_macd_active_date_rejects_warmup_signals(self) -> None:
        from datetime import date
        from research.engine.strategies import ORBRsiMacdShort, ORBRsiMacdShortConfig
        bars = [_bar(index * 5, 100 - index * .03, 100.03 - index * .03,
                     99.97 - index * .03, 100 - index * .03) for index in range(30)]
        self.assertIsNone(ORBRsiMacdShort(ORBRsiMacdShortConfig(active_date=date(2025, 1, 2))).evaluate(bars))

    def test_orb_pullback_emits_once_per_session(self) -> None:
        bars = [
            _bar(0, 100.0, 100.2, 99.8, 100.0), _bar(5, 100.0, 100.3, 99.9, 100.1),
            _bar(10, 100.1, 100.4, 99.9, 100.2), _bar(15, 100.3, 100.8, 100.3, 100.7),
            _bar(20, 100.6, 100.6, 100.35, 100.45), _bar(25, 100.45, 100.85, 100.4, 100.8),
            _bar(30, 100.8, 101.1, 100.7, 101.0),
        ]
        strategy = OpeningRangePullback(OpeningRangePullbackConfig(atr_bars=3))
        first = None
        for index in range(1, len(bars) + 1):
            first = strategy.evaluate(bars[:index])
            if first is not None:
                break
        self.assertIsNotNone(first)
        self.assertIsNone(strategy.evaluate(bars))

    def test_failed_opening_range_reversion_requires_meaningful_break_then_close_inside(self) -> None:
        from research.engine.strategies import FailedOpeningRangeReversion, FailedOpeningRangeReversionConfig
        # First 15 one-minute bars define a 99.8–100.2 range.  A 10:00 close
        # breaks meaningfully above it; the next red minute closes back inside.
        bars = [_bar(index, 100.0, 100.2, 99.8, 100.0) for index in range(15)]
        bars += [_bar(30, 100.0, 100.75, 100.0, 100.65), _bar(31, 100.65, 100.66, 100.05, 100.15)]
        strategy = FailedOpeningRangeReversion(FailedOpeningRangeReversionConfig(
            minimum_excursion_range=.20, minimum_vwap_room_range=.0,
        ))
        signal = None
        for index in range(1, len(bars) + 1):
            signal = strategy.evaluate(bars[:index])
            if signal is not None:
                break
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(Side.SHORT, signal.side)
        self.assertEqual("upward_opening_range_break_failed_back_inside", signal.features["trigger"])

    def test_one_position_research_filter_keeps_only_non_overlapping_markouts(self) -> None:
        rows = [
            {"entry_time": "2026-01-02T10:00:00", "exit_time": "2026-01-02T11:00:00"},
            {"entry_time": "2026-01-02T10:30:00", "exit_time": "2026-01-02T11:30:00"},
            {"entry_time": "2026-01-02T11:00:00", "exit_time": "2026-01-02T12:00:00"},
        ]
        kept = non_overlapping_rows(rows)
        self.assertEqual(["2026-01-02T10:00:00", "2026-01-02T11:00:00"],
                         [row["entry_time"] for row in kept])


if __name__ == "__main__":
    unittest.main()

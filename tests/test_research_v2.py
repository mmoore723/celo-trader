"""Contract tests for the order-free V2 research foundation."""

from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from research_v2.data import load_csv
from research_v2.models import Bar, Side, Signal
from research_v2.providers.alpaca import export_alpaca_csv
from research_v2.simulator import SimulationConfig, Simulator
from research_v2.strategies import TrendContinuation, TrendContinuationConfig
from research_v2.validation import ValidationConfig, validate
from research_v2.walk_forward import run_walk_forward


def _bar(minute: int, o: float, h: float, low: float, c: float) -> Bar:
    return Bar(datetime(2026, 1, 2, 9, 30) + timedelta(minutes=minute), o, h, low, c)


class _OneLong:
    strategy_id = "TEST_LONG"

    def evaluate(self, bars):
        if len(bars) != 2:
            return None
        last = bars[-1]
        return Signal(self.strategy_id, Side.LONG, last.timestamp, last.close, 98, 104, {"setup": "test"})


class ResearchV2Tests(unittest.TestCase):
    def test_signal_fills_next_bar_not_signal_bar(self) -> None:
        bars = [_bar(0, 100, 101, 99, 100), _bar(1, 100, 101, 99, 100),
                _bar(2, 102, 105, 101, 104), _bar(3, 104, 104, 103, 103)]
        trades = Simulator(SimulationConfig(slippage_bps=0)).run(bars, _OneLong())
        self.assertEqual(1, len(trades))
        self.assertEqual(102, trades[0].entry_price)
        self.assertEqual("target", trades[0].exit_reason)

    def test_ambiguous_bar_uses_stop_first(self) -> None:
        bars = [_bar(0, 100, 101, 99, 100), _bar(1, 100, 101, 99, 100),
                _bar(2, 100, 101, 99, 100), _bar(3, 100, 105, 97, 102)]
        trades = Simulator(SimulationConfig(slippage_bps=0)).run(bars, _OneLong())
        self.assertEqual("stop", trades[0].exit_reason)
        self.assertEqual(98, trades[0].exit_price)

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


if __name__ == "__main__":
    unittest.main()

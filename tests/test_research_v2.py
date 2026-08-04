"""Contract tests for the order-free V2 research foundation."""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from research_v2.data import load_csv, resample_regular_session
from research_v2.models import Bar, Side, Signal, Trade
from research_v2.reconciliation import ReferenceTrade, reconcile
from research_v2.ledger import load_trade_ledger, write_trade_ledger
from research_v2.regime import select_regimes
from research_v2.options import OptionQuote, OptionQuoteBook, load_option_quotes
from research_v2.option_markouts import run_databento_cbbo_markouts, run_option_markouts
from research_v2.providers.alpaca import export_alpaca_csv
from research_v2.providers.databento import normalize_databento_cbbo_files
from scripts.research_v2.run_paid_databento_job import archive_filenames, batch_file_date, build_strategy, day_bars, manifest_filenames, summarize
from research_v2.simulator import SimulationConfig, Simulator
from research_v2.strategies import (
    AfternoonReversal, AfternoonReversalConfig, FairValueGap, FairValueGapConfig,
    OpeningRangePullback, OpeningRangePullbackConfig,
    OpeningRangeBreakout, OpeningRangeBreakoutConfig,
    TrendContinuation, TrendContinuationConfig,
)
from research_v2.strategies import VWAPPullback, VWAPPullbackConfig
from research_v2.strategies import SuperTrendReversal
from research_v2.strategies import EMAPullbackRTH, EMAPullbackRTHConfig
from research_v2.strategies import TurtleSoupRTH, TurtleSoupRTHConfig
from research_v2.strategies import GapFillRTH, GapFillRTHConfig
from research_v2.strategies import OpeningMomentumRTH, OpeningMomentumRTHConfig
from research_v2.supertrend_simulator import ReversalSimulationConfig, SuperTrendReversalSimulator
from research_v2.validation import ValidationConfig, validate
from research_v2.walk_forward import run_walk_forward
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

    def test_paid_runner_selects_distinct_orb_hypotheses(self) -> None:
        self.assertEqual("V2_ORB_PULLBACK", build_strategy("orb_pullback").strategy_id)

    def test_orb_pullback_adapter_preserves_structural_stop_and_provenance(self) -> None:
        """The live paper adapter must hand the V2 stop to the normal exit path."""
        from unittest.mock import patch
        import pandas as pd
        from research_v2.models import Signal as V2Signal
        from strategies.orb_pullback_v2 import evaluate

        frame = pd.DataFrame({
            # 15 completed bars ends at 10:40—the first bar the V2 default
            # ATR rule permits and still inside its 10:45 entry deadline.
            "time": pd.date_range("2026-01-02 09:30", periods=15, freq="5min"),
            "open": [100.0] * 15,
            "high": [101.0] * 15,
            "low": [99.0] * 15,
            "close": [100.0] * 15,
            "volume": [1000] * 15,
            "rvol": [1.25] * 15,
        })
        candidate = V2Signal(
            "V2_ORB_PULLBACK", Side.LONG, frame["time"].iloc[-1].to_pydatetime(),
            100.0, 98.0, 104.0, {"trigger": "upward_breakout_first_retest_bounce"},
        )
        with patch("strategies.orb_pullback_v2.OpeningRangePullback.evaluate", return_value=candidate):
            signal = evaluate(frame, "TSLA")

        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual("bullish", signal.direction)
        self.assertEqual(98.0, signal.meta["entry_bar_low"])
        self.assertIsNone(signal.meta["entry_bar_high"])
        self.assertEqual(98.0, signal.meta["v2_stop"])
        self.assertEqual(104.0, signal.meta["v2_target"])
        self.assertEqual("opening_range_pullback", signal.meta["v2_hypothesis"])

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
        # Only a close above the sweep bar's high confirms the long.
        bars.append(_bar(6, 100.6, 101.0, 100.3, 100.8))
        signal = strategy.evaluate(bars)
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(Side.LONG, signal.side)
        self.assertEqual(98.5, signal.stop)

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


if __name__ == "__main__":
    unittest.main()

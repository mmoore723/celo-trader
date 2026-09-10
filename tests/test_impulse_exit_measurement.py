from datetime import datetime
import unittest

import pandas as pd

from strategy_health.impulse_exit import first_exit, executable_bid


def candles(start="2026-09-10T10:05", minutes=130):
    return pd.DataFrame([dict(time=t, open=100, high=101, low=99, close=100)
                         for t in pd.date_range(start, periods=minutes, freq="min")])


class ImpulseExitMeasurementTests(unittest.TestCase):
    def decision(self, frame=None, **changes):
        args = dict(entry_at="2026-09-10T10:05", entry_quote_at="2026-09-10T10:05:03",
                    stop=98, target=104, direction="bullish", now="2026-09-10T10:15")
        args.update(changes)
        return first_exit(candles() if frame is None else frame, **args)

    def test_entry_candle_is_not_an_exit_and_unfinished_candle_is_ignored(self):
        frame = candles()
        frame.loc[0:4, "low"] = 90
        self.assertIsNone(self.decision(frame))
        frame.loc[5, "low"] = 97
        self.assertIsNone(self.decision(frame, now="2026-09-10T10:14:59"))
        self.assertEqual((datetime(2026, 9, 10, 10, 15), "underlying_stop"), self.decision(frame))

    def test_stop_wins_same_bar_ambiguity_for_both_directions(self):
        frame = candles()
        frame.loc[5, ["low", "high"]] = [97, 105]
        self.assertEqual("underlying_stop", self.decision(frame)[1])
        self.assertEqual("underlying_stop", self.decision(frame, direction="bearish", stop=104, target=98)[1])

    def test_long_and_short_targets(self):
        frame = candles()
        frame.loc[5, "high"] = 105
        self.assertEqual("underlying_2r_target", self.decision(frame)[1])
        frame.loc[5, ["high", "low"]] = [101, 97]
        self.assertEqual("underlying_2r_target", self.decision(frame, direction="bearish", stop=104, target=98)[1])

    def test_first_trigger_cannot_be_replaced_by_later_winner(self):
        frame = candles()
        frame.loc[5, "low"] = 97
        frame.loc[10, "high"] = 105
        self.assertEqual((datetime(2026, 9, 10, 10, 15), "underlying_stop"),
                         self.decision(frame, now="2026-09-10T10:25"))

    def test_24_bar_hold_cap_uses_close_not_open(self):
        self.assertIsNone(self.decision(now="2026-09-10T12:05"))
        self.assertEqual((datetime(2026, 9, 10, 12, 10), "time_cap_120m"),
                         self.decision(now="2026-09-10T12:10"))

    def test_session_close_and_last_entry_candle(self):
        self.assertEqual((datetime(2026, 9, 10, 16), "session_flatten"), self.decision(
            candles("2026-09-10T15:00", 60), entry_at="2026-09-10T15:00",
            entry_quote_at="2026-09-10T15:00:01", now="2026-09-10T16:00"))
        self.assertEqual("end_of_available_session", self.decision(
            candles("2026-09-10T15:55", 5), entry_at="2026-09-10T15:55",
            entry_quote_at="2026-09-10T15:55:01", now="2026-09-10T16:00")[1])

    def test_missing_candle_never_infers_a_later_target(self):
        frame = candles().drop(index=6)
        frame.loc[10, "high"] = 105
        self.assertIsNone(self.decision(frame))
        self.assertEqual("missing_bars", self.decision(frame, now="2026-09-10T10:25")[1])

    def test_invalid_inputs_are_not_profit(self):
        self.assertEqual("late_entry_quote", self.decision(entry_quote_at="2026-09-10T10:10")[1])
        self.assertEqual("invalid_entry", self.decision(entry_at="2026-09-10T10:06")[1])
        self.assertEqual("invalid_levels", self.decision(stop=float("nan"))[1])
        frame = candles()
        frame.loc[5, "low"] = 200
        self.assertEqual("invalid_bars", self.decision(frame)[1])
        self.assertEqual("duplicate_bars", self.decision(pd.concat([candles(), candles()]))[1])

    def test_utc_bars_and_entry_convert_to_eastern(self):
        frame = candles()
        frame["time"] = frame["time"].dt.tz_localize("America/New_York").dt.tz_convert("UTC")
        frame.loc[5, "low"] = 97
        self.assertEqual(datetime(2026, 9, 10, 10, 15), self.decision(frame, entry_at="2026-09-10T14:05:00Z")[0])

    def test_quote_requires_contract_fresh_bid_and_causal_window(self):
        args = dict(contract="XYZ", decision_at="2026-09-10T10:15", received_at="2026-09-10T10:16")
        quote = dict(symbol="XYZ", source_symbol="XYZ", bid=1.1, ask=1.2, bid_date="2026-09-10T10:15:30")
        self.assertEqual(1.1, executable_bid(quote, **args)[0])
        for changes in [dict(symbol="OTHER"), dict(source_symbol="OTHER"), dict(source_symbol=None), dict(bid=2), dict(bid=float("inf")),
                        dict(bid_date="2026-09-10T10:14:59"), dict(bid_date="2026-09-10T10:17"),
                        dict(bid_date=None), dict(ask=0)]:
            self.assertIsNone(executable_bid({**quote, **changes}, **args), changes)
        self.assertIsNone(executable_bid(quote, **{**args, "received_at": "2026-09-10T10:21"}))
        self.assertEqual(0, executable_bid({**quote, "bid": 0}, **args)[0])
        epoch = pd.Timestamp("2026-09-10T14:15:30Z").timestamp()*1000
        self.assertEqual(1.1, executable_bid({**quote, "bid_date": epoch}, **args)[0])

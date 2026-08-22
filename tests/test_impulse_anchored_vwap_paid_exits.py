from datetime import datetime, time, timezone
import unittest

from research.engine.models import Bar, Side, Signal
from research.jobs.replay_paid_tsla_impulse_anchored_vwap_exits import intended_exit_plan


def _bars(closes: list[float]) -> tuple[Bar, ...]:
    return tuple(
        Bar(datetime(2026, 1, 2, 10, index * 5, tzinfo=timezone.utc), close, close + 1, close - 1, close, 100)
        for index, close in enumerate(closes)
    )


class IntendedExitPlanTests(unittest.TestCase):
    def test_stop_wins_same_bar_and_order_waits_for_close(self) -> None:
        bars = _bars([100, 100, 100, 100])
        signal = Signal("TEST", Side.LONG, bars[0].timestamp, 100, 99, 101, {})
        plan = intended_exit_plan(bars, signal)
        self.assertEqual("underlying_stop", plan.reason)
        self.assertEqual(bars[2].timestamp.replace(minute=15), plan.time)

    def test_target_and_short_stop_are_direction_aware(self) -> None:
        long_bars = _bars([100, 100, 102, 102])
        long_signal = Signal("TEST", Side.LONG, long_bars[0].timestamp, 100, 97, 101, {})
        self.assertEqual("underlying_2r_target", intended_exit_plan(long_bars, long_signal).reason)
        short_bars = _bars([100, 100, 102, 102])
        short_signal = Signal("TEST", Side.SHORT, short_bars[0].timestamp, 100, 101, 97, {})
        self.assertEqual("underlying_stop", intended_exit_plan(short_bars, short_signal).reason)

    def test_maximum_hold_is_a_cap_not_the_only_exit(self) -> None:
        bars = _bars([100] * 8)
        signal = Signal("TEST", Side.LONG, bars[0].timestamp, 100, 90, 110, {})
        plan = intended_exit_plan(bars, signal, max_hold_bars=3, session_exit_time=time(15, 55))
        self.assertEqual("time_cap_120m", plan.reason)
        self.assertEqual(bars[4].timestamp.replace(minute=25), plan.time)


if __name__ == "__main__":
    unittest.main()

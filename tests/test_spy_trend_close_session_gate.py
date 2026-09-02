from __future__ import annotations

import unittest

from research.jobs.assess_spy_trend_close_session_gate import (
    apply_close_session_gate,
)


def _row(entry_time: str, *, ticker: str = "SPY", strategy_id: str = "V2_SPY_TREND_CONT"):
    return {
        "entry_time": entry_time,
        "ticker": ticker,
        "strategy_id": strategy_id,
    }


class SpyTrendCloseSessionGateTests(unittest.TestCase):
    def test_gate_uses_eastern_time_during_daylight_time(self) -> None:
        rows = [
            _row("2026-07-01T18:59:00+00:00"),
            _row("2026-07-01T19:00:00+00:00"),
        ]
        self.assertEqual([rows[0]], apply_close_session_gate(rows))

    def test_gate_only_blocks_spy_trend(self) -> None:
        rows = [
            _row("2026-07-01T19:05:00+00:00", ticker="TSLA"),
            _row("2026-07-01T19:05:00+00:00", strategy_id="V2_SPY_AFTERNOON_FVG"),
        ]
        self.assertEqual(rows, apply_close_session_gate(rows))

    def test_gate_uses_eastern_time_during_standard_time(self) -> None:
        rows = [
            _row("2026-01-05T19:59:00+00:00"),
            _row("2026-01-05T20:00:00+00:00"),
        ]
        self.assertEqual([rows[0]], apply_close_session_gate(rows))


if __name__ == "__main__":
    unittest.main()

"""Parity checks for the reviewed TSLA adaptive-boundary execution bridge."""
from __future__ import annotations

from datetime import datetime, timedelta
import unittest

import pandas as pd

from trading.noise_momentum_execution import update_noise_momentum


def _session(day: datetime, *, close_at_check: float, close_at_end: float = 100.0) -> list[dict]:
    return [
        {"time": day.replace(hour=9, minute=30), "open": 100.0, "high": 100.2, "low": 99.8, "close": 100.0},
        {"time": day.replace(hour=10, minute=0), "open": 100.0, "high": close_at_check + .1, "low": 99.9, "close": close_at_check},
        {"time": day.replace(hour=15, minute=59), "open": close_at_end, "high": close_at_end + .1, "low": close_at_end - .1, "close": close_at_end},
    ]


class NoiseMomentumExecutionTests(unittest.TestCase):
    def test_requires_exact_fourteen_complete_prior_one_minute_sessions(self) -> None:
        day = datetime(2026, 2, 2)
        history = pd.DataFrame(sum((_session(day + timedelta(days=i), close_at_check=100.0) for i in range(13)), []))
        today = pd.DataFrame(_session(day + timedelta(days=13), close_at_check=103.0))
        signal, status = update_noise_momentum({}, history, today, ticker="TSLA", now=today["time"].iloc[1] + timedelta(minutes=1))
        self.assertIsNone(signal)
        self.assertEqual("waiting_for_14_complete_one_minute_sessions", status)

    def test_emits_only_after_completed_boundary_transition_and_only_once(self) -> None:
        day = datetime(2026, 2, 2)
        history = pd.DataFrame(sum((_session(day + timedelta(days=i), close_at_check=100.0) for i in range(14)), []))
        today = pd.DataFrame(_session(day + timedelta(days=14), close_at_check=103.0))
        state: dict[str, object] = {}
        now = today["time"].iloc[1] + timedelta(minutes=1)
        signal, status = update_noise_momentum(state, history, today, ticker="TSLA", now=now)
        self.assertEqual("completed_boundary_transition", status)
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual("V2_TSLA_NOISE_MOMENTUM", signal.strategy_id)
        self.assertEqual("bullish", signal.direction)
        self.assertEqual("completed_1m_boundary_transition_then_next_minute", signal.meta["entry_timing"])
        repeated, repeated_status = update_noise_momentum(state, history, today, ticker="TSLA", now=now)
        self.assertIsNone(repeated)
        self.assertEqual("already_emitted", repeated_status)

    def test_does_not_replace_tsla_history_with_another_ticker(self) -> None:
        signal, status = update_noise_momentum({}, pd.DataFrame(), pd.DataFrame(), ticker="SPY", now=datetime(2026, 2, 2, 10, 1))
        self.assertIsNone(signal)
        self.assertEqual("not_applicable", status)


if __name__ == "__main__":
    unittest.main()

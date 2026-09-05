"""Performance results must not blend an old account into the current one."""

from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from api.routes.trades import get_analytics, get_performance, _strategy_version_from_trade_row
from database.schema import _init_db_at
from database.trades_query import get_all_trades as read_all_trades


class PerformanceAccountScopeTests(unittest.TestCase):
    @patch("config.get_settings", return_value={"active_broker_account_id": "alpaca:paper:current"})
    @patch("database.get_all_trades")
    def test_current_account_scope_is_reported(self, get_all_trades, _get_settings):
        get_all_trades.return_value = []

        result = get_performance("paper")

        self.assertTrue(result.account_scoped)
        self.assertIn("currently connected", result.data_scope_note)
        get_all_trades.assert_called_once_with(
            limit=1000, mode="paper", broker_account_id="alpaca:paper:current",
        )

    def test_strategy_version_prefers_frozen_trade_context(self):
        self.assertEqual("2.1.0", _strategy_version_from_trade_row({
            "strategy_context_json": '{"strategy_version":"2.1.0"}',
            "candidate_strategy_version": "2.0.0",
        }))
        self.assertEqual("2.0.0", _strategy_version_from_trade_row({
            "strategy_context_json": None,
            "candidate_strategy_version": "2.0.0",
        }))
        self.assertIsNone(_strategy_version_from_trade_row({
            "strategy_context_json": None,
            "candidate_strategy_version": None,
        }))

    def test_trade_reader_joins_candidate_strategy_version(self):
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "trades_paper.db"
            _init_db_at(db_path)
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    """INSERT INTO shadow_candidates
                       (candidate_id, observed_at, ticker, strategy_id, direction,
                        confidence, metadata_json, final_outcome)
                       VALUES ('candidate-1', '2026-09-05T10:00:00-04:00', 'SPY',
                               'V2_SPY_TREND_CONT', 'bullish', 0.8,
                               '{"strategy_version":"2.1.0"}', 'entered')"""
                )
                conn.execute(
                    """INSERT INTO trades
                       (ticker, contract_symbol, option_type, strike, expiry,
                        contracts, entry_price, entry_time, status, paper,
                        strategy_id, broker_account_id, candidate_id)
                       VALUES ('SPY', 'SPY260912C00770000', 'call', 770,
                               '2026-09-12', 1, 3.5,
                               '2026-09-05T10:00:01-04:00', 'closed', 1,
                               'V2_SPY_TREND_CONT', 'paper:current', 'candidate-1')"""
                )
            with patch("database.connection.get_db_path", return_value=db_path):
                rows = read_all_trades(
                    mode="paper", status_filter="closed",
                    broker_account_id="paper:current",
                )

        self.assertEqual(1, len(rows))
        self.assertEqual("2.1.0", rows[0]["candidate_strategy_version"])

    @patch("config.get_settings", return_value={"active_broker_account_id": "alpaca:paper:current"})
    @patch("database.get_all_trades")
    def test_strategy_analytics_separates_current_version_from_old_history(
        self, get_all_trades, _get_settings,
    ):
        get_all_trades.return_value = [
            {
                "strategy_id": "V2_SPY_TREND_CONT", "realized_pnl": 44,
                "candidate_strategy_version": "2.1.0", "strategy_context_json": None,
            },
            {
                "strategy_id": "V2_SPY_TREND_CONT", "realized_pnl": -219,
                "candidate_strategy_version": "2.0.0", "strategy_context_json": None,
            },
            {
                "strategy_id": "V2_SPY_TREND_CONT", "realized_pnl": 30,
                "candidate_strategy_version": None, "strategy_context_json": None,
            },
        ]

        result = get_analytics("paper")
        row = next(item for item in result.by_strategy if item.strategy_id == "V2_SPY_TREND_CONT")

        self.assertEqual(3, row.trades)
        self.assertEqual("2.1.0", row.current_version)
        self.assertEqual(1, row.current_version_trades)
        self.assertEqual(1, row.current_version_wins)
        self.assertEqual(0, row.current_version_losses)
        self.assertEqual(44, row.current_version_total_pnl)
        self.assertEqual(2, row.prior_or_unversioned_trades)


if __name__ == "__main__":
    unittest.main()

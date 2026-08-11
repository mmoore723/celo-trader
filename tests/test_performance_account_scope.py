"""Performance results must not blend an old account into the current one."""

import unittest
from unittest.mock import patch

from api.routes.trades import get_performance


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


if __name__ == "__main__":
    unittest.main()

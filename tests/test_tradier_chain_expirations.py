from datetime import date
import unittest
from unittest.mock import patch

from broker.tradier_chain import TradierChainMixin


class _ChainClient(TradierChainMixin):
    api_key = "production-market-token"

    def _get(self, _endpoint, _params):
        return {"expirations": {"date": [
            "2026-09-09", "2026-09-11", "2026-09-14",
            "2026-09-16", "2026-09-23", "2026-10-02",
        ]}}


class TradierExpirationWindowTests(unittest.TestCase):
    @patch("broker.tradier_chain._market_date", return_value=date(2026, 9, 9))
    def test_default_window_preserves_reviewed_order_policy(self, _clock):
        self.assertEqual(
            ["2026-09-16", "2026-09-23"],
            _ChainClient().get_expirations("SPY"),
        )

    @patch("broker.tradier_chain._market_date", return_value=date(2026, 9, 9))
    def test_research_can_request_same_week_expirations(self, _clock):
        self.assertEqual(
            ["2026-09-09", "2026-09-11", "2026-09-14"],
            _ChainClient().get_expirations(
                "SPY", minimum_dte=0, maximum_dte=5, limit=8,
            ),
        )


if __name__ == "__main__":
    unittest.main()

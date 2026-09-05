from datetime import datetime
import unittest
from unittest.mock import patch

from trading.research_contract_selection import (
    RESEARCH_MAX_CONTRACT_DOLLARS, research_contract_profile,
    select_research_contract,
)


class _Tradier:
    def __init__(self, expirations, chains):
        self.expirations = expirations
        self.chains = chains

    def get_expirations(self, _ticker):
        return self.expirations

    def get_option_chain(self, _ticker, expiry, _option_type):
        return self.chains.get(expiry, [])


class ResearchContractSelectionTests(unittest.TestCase):
    def test_context_orb_collects_same_week_150_to_1000_and_prefers_target_band(self):
        tradier = _Tradier(["2026-09-04", "2026-09-11"], {
            "2026-09-04": [
                {"symbol": "AAPL_A", "strike": 101, "bid": 1.91, "ask": 1.95, "spread": .04, "open_interest": 50, "volume": 25},
                {"symbol": "AAPL_B", "strike": 102, "bid": 8.90, "ask": 9.00, "spread": .10, "open_interest": 500, "volume": 250},
            ],
            "2026-09-11": [
                {"symbol": "AAPL_LATE", "strike": 101, "bid": 1.99, "ask": 2.00, "spread": .01},
            ],
        })
        with patch("trading.research_contract_selection._now_et", return_value=datetime(2026, 9, 1, 10)):
            selected, info = select_research_contract(
                tradier, "AAPL", "bullish", 100.0, "CTX_ORB_NR7_OR_INSIDE",
            )
        self.assertEqual("AAPL_A", selected["symbol"])
        self.assertEqual("target_150_250", info["selected_policy"])
        self.assertEqual(2, info["eligible_contract_count"])
        policies = {
            policy
            for row in info["shadow_contract_leaderboard"]
            for policy in row["policy_winner_for"]
        }
        self.assertIn("target_150_250", policies)
        self.assertIn("closest_otm_150_1000", policies)
        self.assertEqual(1000.0, info["research_profile"]["maximum_contract_dollars"])

    def test_squeeze_enforces_three_to_five_dte(self):
        profile = research_contract_profile("CTX_1H_SQUEEZE_MACD_LONG")
        self.assertEqual((3, 5), (profile.minimum_dte, profile.maximum_dte))
        tradier = _Tradier(["2026-09-02", "2026-09-04"], {
            "2026-09-02": [
                {"symbol": "QQQ_1D", "strike": 701, "bid": 1.9, "ask": 2.0, "spread": .1},
            ],
            "2026-09-04": [
                {"symbol": "QQQ_3D", "strike": 701, "bid": 1.9, "ask": 2.0, "spread": .1},
            ],
        })
        with patch("trading.research_contract_selection._now_et", return_value=datetime(2026, 9, 1, 10)):
            selected, _ = select_research_contract(
                tradier, "QQQ", "bullish", 700.0, "CTX_1H_SQUEEZE_MACD_LONG",
            )
        self.assertEqual("QQQ_3D", selected["symbol"])

    def test_research_selector_accepts_any_collected_ticker_without_order_authority(self):
        tradier = _Tradier(["2026-09-04"], {
            "2026-09-04": [
                {"symbol": "ABNB_P", "strike": 149, "bid": 1.9, "ask": 2.0, "spread": .1},
            ],
        })
        with patch("trading.research_contract_selection._now_et", return_value=datetime(2026, 9, 1, 10)):
            selected, info = select_research_contract(
                tradier, "ABNB", "bearish", 150.0, "V2_SPY_TREND_CONT",
            )
        self.assertEqual("ABNB_P", selected["symbol"])
        self.assertEqual("selected", info["reason"])
        self.assertEqual(RESEARCH_MAX_CONTRACT_DOLLARS, info["research_profile"]["maximum_contract_dollars"])


if __name__ == "__main__":
    unittest.main()

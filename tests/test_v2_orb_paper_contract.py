"""Regression tests for the V2 paid-study-aligned paper contract selector."""
from __future__ import annotations

from datetime import date, timedelta
import unittest

from trading.entry.contract import select_v2_orb_paper_contract


class _FakeTradier:
    def __init__(self, chains: dict[str, list[dict]]) -> None:
        self._chains = chains
        self._expirations = list(chains)

    def get_expirations(self, _ticker: str) -> list[str]:
        return self._expirations

    def get_option_chain(self, _ticker: str, expiry: str, _option_type: str) -> list[dict]:
        return self._chains[expiry]


class V2OrbPaperContractTests(unittest.TestCase):
    def test_selects_nearest_expiry_then_nearest_otm_contract(self) -> None:
        near = (date.today() + timedelta(days=7)).isoformat()
        later = (date.today() + timedelta(days=14)).isoformat()
        broker = _FakeTradier({
            later: [{"symbol": "TSLA_LATER", "strike": 250, "bid": 2.80, "ask": 3.00}],
            near: [
                {"symbol": "TSLA_TOO_CHEAP", "strike": 249, "bid": 0.60, "ask": 0.70},
                {"symbol": "TSLA_NEAR", "strike": 251, "bid": 2.90, "ask": 3.00},
                {"symbol": "TSLA_FAR", "strike": 260, "bid": 3.80, "ask": 4.00},
            ],
        })
        contract, info = select_v2_orb_paper_contract(broker, "TSLA", "bullish", 250, 500)
        self.assertEqual("selected", info["reason"])
        self.assertEqual("TSLA_NEAR", contract["symbol"])
        self.assertEqual(7, info["selected_dte"])
        self.assertEqual("v2_orb_paid_tsla_near_money_otm_v1", contract["selection_model"])

    def test_rejects_non_tsla_and_wide_spread(self) -> None:
        expiry = (date.today() + timedelta(days=7)).isoformat()
        broker = _FakeTradier({expiry: [{"symbol": "TSLA_WIDE", "strike": 251, "bid": 2.00, "ask": 3.00}]})
        contract, info = select_v2_orb_paper_contract(broker, "QQQ", "bullish", 250, 500)
        self.assertIsNone(contract)
        self.assertEqual("unsupported_v2_ticker", info["reason"])
        contract, info = select_v2_orb_paper_contract(broker, "TSLA", "bullish", 250, 500)
        self.assertIsNone(contract)
        self.assertEqual("illiquid", info["reason"])


if __name__ == "__main__":
    unittest.main()

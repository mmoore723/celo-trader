import unittest

from scripts.research_v2.compare_paid_portfolio import _account_summary, _route


def trade(name: str, entry: str, exit_time: str, ask: float, bid: float) -> dict[str, object]:
    return {
        "strategy": name,
        "signal_time": entry,
        "entry_time": entry,
        "exit_time": exit_time,
        "entry_ask": ask,
        "exit_bid": bid,
        "return_pct": (bid / ask - 1) * 100,
    }


class PaidPortfolioTests(unittest.TestCase):
    def test_unaffordable_early_signal_does_not_reserve_a_slot(self):
        early = trade("v2_orb_pullback", "2026-01-02T10:00:00-05:00", "2026-01-02T11:30:00-05:00", 8.0, 8.0)
        affordable = trade("v2_trend_continuation", "2026-01-02T10:01:00-05:00", "2026-01-02T11:31:00-05:00", 5.0, 6.0)
        accepted = _route(
            [early, affordable], max_positions=1,
            priority=("v2_orb_pullback", "v2_trend_continuation"),
            starting_capital=5_000, allocation_fraction=.15,
        )
        self.assertEqual([affordable], accepted)

    def test_cash_summary_never_borrows_for_an_unaffordable_contract(self):
        result = _account_summary(
            [trade("v2_orb_pullback", "2026-01-02T10:00:00-05:00", "2026-01-02T11:00:00-05:00", 8.0, 9.0)],
            starting_capital=5_000, allocation_fraction=.15,
        )
        self.assertEqual(0, result["entered_trades"])
        self.assertEqual(1, result["skipped_unaffordable"])
        self.assertEqual(5_000, result["ending_cash"])


if __name__ == "__main__":
    unittest.main()

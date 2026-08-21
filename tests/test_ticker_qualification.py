import unittest
from datetime import datetime, timedelta

from strategy_health.ticker_qualification import qualify_pair, normalize_completed_observations


def observations(*, positive=True, version="2.0.0", duplicate=False):
    rows = []
    start = datetime(2026, 1, 2, 10, 0)
    for index in range(40):
        moment = start + timedelta(days=index // 2, minutes=index % 2)
        # Distributed winners prevent one lucky trade from qualifying a pair.
        win = positive and index % 4 != 0
        entry, exit_bid = 2.0, (2.20 if win else 1.90)
        row = {
            "candidate_id": f"c{index}", "strategy_id": "V2_SPY_TREND_CONT",
            "strategy_version": version, "ticker": "QQQ",
            "observed_at": moment.isoformat(), "contract_symbol": f"QQQ{index:03d}",
            "entry_ask": entry, "exit_bid": exit_bid,
        }
        rows.append(row)
        if duplicate:
            rows.append({**row, "candidate_id": f"other-account-{index}"})
    return rows


class TickerQualificationTests(unittest.TestCase):
    def test_qualifies_only_with_positive_chronological_holdout(self):
        result = qualify_pair("V2_SPY_TREND_CONT", "QQQ", observations())
        self.assertEqual(result["decision"], "qualified")
        self.assertGreaterEqual(result["training"]["trading_days"], 10)
        self.assertGreaterEqual(result["holdout"]["observations"], 10)

    def test_rejects_negative_training_and_holdout(self):
        result = qualify_pair("V2_SPY_TREND_CONT", "QQQ", observations(positive=False))
        self.assertEqual(result["decision"], "rejected")
        self.assertIn("holdout_profit_factor", result["reasons"])

    def test_old_or_unversioned_rows_cannot_qualify_current_code(self):
        result = qualify_pair("V2_SPY_TREND_CONT", "QQQ", observations(version="1.0.0"))
        self.assertEqual(result["decision"], "insufficient_evidence")
        self.assertEqual(result["exclusions"]["version_mismatch_or_missing"], 40)

    def test_cross_account_duplicates_do_not_inflate_sample(self):
        normalized, _ = normalize_completed_observations(observations(duplicate=True))
        self.assertEqual(len(normalized), 40)

    def test_missing_executable_bid_is_excluded(self):
        rows = observations()
        rows[0]["exit_bid"] = None
        normalized, exclusions = normalize_completed_observations(rows)
        self.assertEqual(len(normalized), 39)
        self.assertEqual(exclusions["missing_exit_bid"], 1)


if __name__ == "__main__":
    unittest.main()

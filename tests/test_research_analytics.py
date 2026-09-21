import unittest

from strategy_health.research_analytics import build_analytics, build_results_page


def pair(ticker, results, wins, profit, loss, net, diagnosis="more_data", status="collecting"):
    return {
        "ticker": ticker, "option_results": results, "wins": wins,
        "gross_profit": profit, "gross_loss": loss, "net_one_contract_pnl": net,
        "profit_factor": "infinite" if results and loss == 0 and profit else round(profit / loss, 2) if loss else None,
        "raw_observations": results + 2, "setups": results + 1,
        "diagnosis": diagnosis, "status": status,
    }


class ResearchAnalyticsTest(unittest.TestCase):
    def setUp(self):
        self.matrix = {
            "target_profit_factor": 1.5, "start_date": "2026-09-01", "end_date": "2026-09-21",
            "strategies": [
                {"strategy_id": "ONE", "display_name": "One", "pairs": [pair("META", 3, 2, 100, 40, 60, status="promising"), pair("SPY", 2, 0, 0, 50, -50, "exit", "losing_so_far")]},
                {"strategy_id": "TWO", "display_name": "Two", "pairs": [pair("TSLA", 1, 1, 30, 0, 30)]},
            ],
            "days": 21, "ticker_count": 3, "strategy_count": 2,
        }

    def test_analytics_uses_global_gross_profit_and_loss(self):
        result = build_analytics(self.matrix)
        self.assertEqual(result["summary"]["priced_tests"], 6)
        self.assertEqual(result["summary"]["wins"], 3)
        self.assertEqual(result["summary"]["profit_factor"], 1.44)
        self.assertEqual(result["summary"]["net_pnl"], 40)
        self.assertEqual(result["top_tickers"][0]["ticker"], "META")
        self.assertEqual(result["bottom_tickers"][0]["ticker"], "SPY")

    def test_filters_are_applied_before_aggregation(self):
        result = build_analytics(self.matrix, tickers={"META"}, statuses={"at_goal"})
        self.assertEqual(result["summary"]["priced_tests"], 3)
        self.assertEqual([row["ticker"] for row in result["tickers"]], ["META"])

    def test_results_are_paginated_after_server_filters(self):
        result = build_results_page(self.matrix, page=1, page_size=1, ticker="", result_filter="results")
        self.assertEqual(result["pagination"], {"page": 1, "page_size": 1, "total": 3, "has_more": True})
        self.assertEqual(sum(len(strategy["pairs"]) for strategy in result["strategies"]), 1)
        self.assertEqual(result["result_counts"]["attention"], 1)
        self.assertEqual(len(result["available_strategies"]), 2)

    def test_pair_progress_and_health_use_recorded_counts(self):
        original = self.matrix["strategies"][0]["pairs"][0]
        original.update({"recommendation": {"completed_trades": 3, "independent_trades": 2},
                         "median_one_contract_pnl": 12.5,
                         "authored_exit_evidence": {"tracked": 10, "collecting": 4,
                             "missing_quote": 1, "pending_quote": 1,
                             "reasons": {"missing_bars": 2, "late_entry_quote": 1,
                                         "underlying_2r_target": 2}}})
        result = build_analytics(self.matrix)
        row = next(row for row in result["pairs"] if row["ticker"] == "META")
        self.assertEqual(row["independent_tests"], 2)
        self.assertEqual(row["target_tests"], 20)
        self.assertEqual(row["typical_profit"], 12.5)
        self.assertEqual(row["target_2r_hits"], 2)
        self.assertEqual(result["summary"]["active_tests"], 4)
        self.assertEqual(result["data_quality"]["affected_pct"], 30)
        self.assertEqual(result["data_quality"]["covered_pairs"], 1)
        self.assertEqual(result["pipeline"], {"raw_triggers": 12, "distinct_plays": 9,
                                              "priced_results": 6, "completed_tests": 6})

    def test_analytics_status_does_not_change_results_status(self):
        pair_row = self.matrix["strategies"][0]["pairs"][0]
        pair_row.update({"profit_factor": 1.2, "diagnosis": "price_data"})
        result = build_analytics(self.matrix, statuses={"collecting"})
        self.assertEqual([row["ticker"] for row in result["pairs"]], ["META"])
        self.assertEqual(build_results_page(self.matrix, page=1, page_size=10)["result_counts"]["attention"], 2)

    def test_unique_tickers_and_empty_unknown_health(self):
        self.matrix["strategies"][1]["pairs"].append(pair("META", 1, 1, 5, 0, 5))
        result = build_analytics(self.matrix)
        self.assertEqual(len(result["tickers"]), 3)
        self.assertEqual(result["tickers"][0]["net_pnl"], 65)
        self.assertIsNone(result["data_quality"]["affected_pct"])
        self.assertIsNone(result["pairs"][0]["target_2r_hits"])
        empty = build_analytics(self.matrix, tickers={"NONE"})
        self.assertEqual(empty["pairs"], [])
        self.assertIsNone(empty["summary"]["profit_factor"])


if __name__ == "__main__":
    unittest.main()

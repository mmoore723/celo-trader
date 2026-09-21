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


if __name__ == "__main__":
    unittest.main()

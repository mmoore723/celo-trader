import unittest
from datetime import date

from scanner.strategy_premarket import multi_timeframe_context, strategy_aware_plan


def daily(closes, ranges=None):
    ranges = ranges or [2.0] * len(closes)
    return [
        {"o": close - 0.2, "h": close + width / 2, "l": close - width / 2, "c": close, "v": 1_000_000}
        for close, width in zip(closes, ranges)
    ]


class StrategyPremarketTests(unittest.TestCase):
    def test_five_timeframes_use_only_supplied_market_history(self):
        context = multi_timeframe_context(
            minute_bars=daily([100, 101, 102]),
            hourly_bars=daily([90, 95, 100]),
            daily_bars=daily(list(range(80, 104))),
            current_price=104,
        )
        self.assertEqual(["Minute", "Hour", "Day", "Week", "Month"], [row["label"] for row in context])
        self.assertTrue(all(row["bias"] == "up" for row in context))

    def test_partial_current_daily_candle_is_not_used_as_prior_day(self):
        rows = daily([90, 100, 60])
        rows[0]["is_complete"] = True
        rows[1]["is_complete"] = True
        rows[2].update({"session": date.today().isoformat(), "is_complete": False})
        context = multi_timeframe_context(
            minute_bars=[], hourly_bars=[], daily_bars=rows, current_price=110,
        )
        day = next(row for row in context if row["label"] == "Day")
        self.assertEqual(10.0, day["change_pct"])

    def test_ker_strategy_reports_the_measured_hourly_filter(self):
        context = [{"label": name, "bias": "up", "change_pct": 1.0}
                   for name in ("Minute", "Hour", "Day", "Week", "Month")]
        plan = strategy_aware_plan(
            ticker="AMZN", context=context, daily_bars=daily(range(90, 101)),
            hourly_bars=daily(range(100, 111)), gap_pct=0.2, rvol=1.2,
            executable_strategy_ids=set(), research_strategy_ids={"CTX_VWAP_PULLBACK_KER10_LONG"},
        )
        self.assertIn("1.00", plan["best_strategy"]["reason"])
        self.assertIn("readiness_score", plan["best_strategy"])

    def test_authorized_strategy_wins_ranking_over_research_only_match(self):
        context = [{"label": name, "bias": "up", "change_pct": 1.0}
                   for name in ("Minute", "Hour", "Day", "Week", "Month")]
        plan = strategy_aware_plan(
            ticker="SPY", context=context, daily_bars=daily(range(90, 99)),
            gap_pct=0.8, rvol=1.8,
            executable_strategy_ids={"V2_SPY_AFTERNOON_FVG"},
            research_strategy_ids={"CTX_ORB_NR7_OR_INSIDE"},
        )
        self.assertTrue(plan["tradeable_today"])
        self.assertEqual("V2_SPY_AFTERNOON_FVG", plan["best_strategy"]["strategy_id"])
        self.assertIn("1:30–3:00 PM", plan["entry_note"])

    def test_research_match_cannot_be_presented_as_an_order(self):
        context = [{"label": name, "bias": "flat", "change_pct": 0.0}
                   for name in ("Minute", "Hour", "Day", "Week", "Month")]
        plan = strategy_aware_plan(
            ticker="QQQ", context=context,
            daily_bars=daily(range(100, 108), [4, 3.5, 3, 2.5, 2, 1.5, 0.5, 1]),
            gap_pct=0.2, rvol=1.0,
            executable_strategy_ids=set(), research_strategy_ids={"CTX_1H_SQUEEZE_MACD_LONG"},
        )
        self.assertFalse(plan["tradeable_today"])
        self.assertIn("finished one-hour candle", plan["entry_note"])
        self.assertIn("no early stop", plan["stop_note"].lower())
        self.assertIn("90 minutes", plan["target_note"])
        self.assertIn("executable bid", plan["target_note"])
        self.assertFalse(plan["strategy_matches"][0]["can_trade"])

    def test_research_plan_shows_the_real_strategy_trigger_not_permission_copy(self):
        context = [{"label": name, "bias": "up", "change_pct": 1.0}
                   for name in ("Minute", "Hour", "Day", "Week", "Month")]
        plan = strategy_aware_plan(
            ticker="AMZN", context=context, daily_bars=daily(range(90, 101)),
            hourly_bars=daily(range(100, 111)), gap_pct=0.2, rvol=1.2,
            executable_strategy_ids=set(), research_strategy_ids={"CTX_VWAP_PULLBACK_KER10_LONG"},
        )
        self.assertFalse(plan["tradeable_today"])
        self.assertIn("KER check must pass", plan["entry_note"])
        self.assertNotIn("cannot place an order", plan["entry_note"])
        self.assertIn("after costs", plan["target_note"])

    def test_tradable_displacement_plan_separates_stop_and_profit_target(self):
        context = [{"label": name, "bias": "up", "change_pct": 1.0}
                   for name in ("Minute", "Hour", "Day", "Week", "Month")]
        plan = strategy_aware_plan(
            ticker="AMZN", context=context, daily_bars=daily(range(90, 101)),
            hourly_bars=daily(range(100, 111)), gap_pct=0.2, rvol=1.2,
            executable_strategy_ids={"CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG"},
            research_strategy_ids=set(),
        )
        self.assertTrue(plan["tradeable_today"])
        self.assertIn("below VWAP", plan["stop_note"])
        self.assertIn("high that was set", plan["target_note"])

    def test_no_generic_orb_plan_is_invented_for_unknown_ticker(self):
        plan = strategy_aware_plan(
            ticker="NONE", context=[], daily_bars=[], gap_pct=0, rvol=0,
            executable_strategy_ids=set(), research_strategy_ids=set(),
        )
        self.assertEqual(0, plan["fit_score"])
        self.assertNotIn("ORB", plan["entry_note"])
        self.assertEqual("No entry means no stop.", plan["stop_note"])


if __name__ == "__main__":
    unittest.main()

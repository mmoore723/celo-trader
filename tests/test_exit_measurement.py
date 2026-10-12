import unittest

from config.strategy_catalog import REVIEWED_STRATEGIES
from strategy_health.exit_measurement import exit_measurement
from trading.tested_strategy_research import TESTED_RESEARCH_STRATEGIES


class ExitMeasurementTests(unittest.TestCase):
    def test_fixed_timer_strategy_labels_its_real_exit(self):
        result = exit_measurement("V2_SPY_AFTERNOON_FVG", 30)
        self.assertEqual("strategy_exit", result["kind"])
        self.assertEqual("30-min PF", result["pf_label"])
        self.assertTrue(result["authored_exit_collected"])

    def test_structural_strategy_labels_timer_as_a_check(self):
        result = exit_measurement("TV_SUPERTREND_REVERSAL_V4", 90)
        self.assertEqual("timed_comparison", result["kind"])
        self.assertEqual("90-min check PF", result["pf_label"])
        self.assertFalse(result["authored_exit_collected"])
        self.assertIn("opposite SuperTrend flip", result["authored_exit"])

    def test_every_catalog_strategy_has_an_explicit_exit_description(self):
        from config.research_order_specs import SPECS
        catalog = {SPECS[sid].source if sid in SPECS else sid for sid in set(REVIEWED_STRATEGIES) | set(TESTED_RESEARCH_STRATEGIES)}
        self.assertEqual(26, len(catalog))
        for strategy_id in catalog:
            result = exit_measurement(strategy_id, 90)
            self.assertNotEqual(
                "Exit at the stop or target defined by the strategy.",
                result["authored_exit"],
                strategy_id,
            )


if __name__ == "__main__":
    unittest.main()

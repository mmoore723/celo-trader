from __future__ import annotations

from datetime import date
import unittest

from research.jobs.assess_paid_indicator_filter_value import assess_filter_value


def rows(training, later):
    output = []
    for index, value in enumerate(training, 1):
        output.append({"signal_time": f"2026-01-{index:02d}T10:00:00-05:00", "return_pct": value})
    for index, value in enumerate(later, 1):
        output.append({"signal_time": f"2026-07-{index:02d}T10:00:00-04:00", "return_pct": value})
    return output


class IndicatorFilterValueTests(unittest.TestCase):
    def test_keeps_base_when_filters_do_not_improve_training(self) -> None:
        base = rows([2, 1, -1] * 5, [2, 1, -1] * 4)
        variants = {
            "base": base,
            "rsi_14_aligned": base,
            "macd_12_26_9_aligned": base,
            "rsi_and_macd_aligned": base,
        }
        result = assess_filter_value(variants, date(2026, 7, 1))
        self.assertEqual(result["decision"], "keep_base")
        self.assertFalse(result["indicator_entry_gate"])

    def test_promotes_filter_only_when_early_and_later_results_improve(self) -> None:
        base = rows([3, 2, -4] * 5, [3, 2, -4, 1] * 3)
        good = rows([3, 2] * 8, [3, 2] * 5)
        variants = {
            "base": base,
            "rsi_14_aligned": good,
            "macd_12_26_9_aligned": base,
            "rsi_and_macd_aligned": base,
        }
        result = assess_filter_value(variants, date(2026, 7, 1))
        self.assertEqual(result["decision"], "promote_filter")
        self.assertEqual(result["selected_variant"], "rsi_14_aligned")
        self.assertTrue(result["indicator_entry_gate"])

    def test_rejects_training_winner_that_fails_later(self) -> None:
        base = rows([3, 2, -4] * 5, [3, 2, -1] * 4)
        early_only = rows([3, 2] * 8, [1, -4] * 5)
        variants = {
            "base": base,
            "rsi_14_aligned": early_only,
            "macd_12_26_9_aligned": base,
            "rsi_and_macd_aligned": base,
        }
        result = assess_filter_value(variants, date(2026, 7, 1))
        self.assertEqual(result["decision"], "keep_base")
        self.assertEqual(result["training_selected_variant"], "rsi_14_aligned")
        self.assertFalse(result["indicator_entry_gate"])


if __name__ == "__main__":
    unittest.main()

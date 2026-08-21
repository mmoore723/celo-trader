import unittest
from datetime import date
from types import SimpleNamespace

from research.jobs.assess_paid_price_action_three_period import assess


def _context(*, balanced=False, directional=False):
    return SimpleNamespace(
        momentum_long=directional, momentum_short=False,
        bullish_engulfing=False, bearish_engulfing=False,
        bullish_rejection=False, bearish_rejection=False,
        hammer=False, inverted_hammer=False, shooting_star=False, hanging_man=False,
        bullish_harami=False, bearish_harami=False, morning_star=False, evening_star=False,
        bullish_marubozu=False, bearish_marubozu=False,
        three_white_soldiers=False, three_black_crows=False,
        bullish_failed_break=False, bearish_failed_break=False,
        consecutive_higher_lows=False, consecutive_lower_highs=False,
        resistance_distance_atr=1.0, support_distance_atr=1.0,
        close_location=.8, close_to_fast_ema_atr=.2 if balanced else -.2,
        close_to_vwap_atr=.2 if balanced else -.2, body_to_range=.7,
    )


def _rows(day, count, value, context):
    return [({"signal_time": f"{day}T10:30:00", "side": "long", "return_pct": value}, context)
            for _ in range(count)]


class PriceActionThreePeriodTests(unittest.TestCase):
    def test_promotes_only_when_frozen_filter_beats_baseline_in_both_grades(self):
        enriched = []
        for day in ("2026-01-10", "2026-02-10", "2026-03-10"):
            enriched += _rows(day, 10, 1.0, _context())
            enriched += _rows(day, 10, 3.0, _context(balanced=True))
        result = assess(enriched, selection_end=date(2026, 2, 1), validation_end=date(2026, 3, 1),
                        minimum_selection=10, minimum_grade=10)
        self.assertEqual(result["decision"], "router_candidate")
        self.assertEqual(result["selected_context"], "balanced_price_action")
        self.assertTrue(result["validation_passed"])
        self.assertTrue(result["later_passed"])

    def test_rejects_when_latest_period_does_not_improve_baseline(self):
        enriched = []
        enriched += _rows("2026-01-10", 10, 1.0, _context())
        enriched += _rows("2026-01-10", 10, 3.0, _context(balanced=True))
        enriched += _rows("2026-02-10", 10, 1.0, _context())
        enriched += _rows("2026-02-10", 10, 3.0, _context(balanced=True))
        enriched += _rows("2026-03-10", 10, 3.0, _context())
        enriched += _rows("2026-03-10", 10, 1.0, _context(balanced=True))
        result = assess(enriched, selection_end=date(2026, 2, 1), validation_end=date(2026, 3, 1),
                        minimum_selection=10, minimum_grade=10)
        self.assertEqual(result["decision"], "reject")
        self.assertTrue(result["validation_passed"])
        self.assertFalse(result["later_passed"])


if __name__ == "__main__":
    unittest.main()

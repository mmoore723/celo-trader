from datetime import date
import unittest

from research.jobs.assess_paid_tsla_orb_retouch_contexts import _matches, _select


def row(day: str, result: float, *, delay: float = 10, extension: float = .5) -> dict[str, object]:
    return {
        "signal_time": f"{day}T10:00:00-05:00", "return_pct": result, "side": "long",
        "retest_delay_minutes": delay, "breakout_extension_ranges": extension,
    }


class PaidTslaOrbRetouchContextTests(unittest.TestCase):
    def test_contexts_only_keep_long_entries_with_required_visible_facts(self):
        fast_decisive = row("2026-01-02", 2, delay=8, extension=.4)
        slow = row("2026-01-03", 2, delay=16, extension=.4)
        weak = row("2026-01-04", 2, delay=8, extension=.2)
        short = dict(fast_decisive, side="short")
        self.assertTrue(_matches(fast_decisive, "prompt_decisive_long_retouches"))
        self.assertFalse(_matches(slow, "prompt_long_retouches"))
        self.assertFalse(_matches(weak, "decisive_long_breakouts"))
        self.assertFalse(_matches(short, "all_long_retouches"))

    def test_selection_uses_earlier_period_not_later_outcomes(self):
        contexts = {
            "all_long_retouches": [row(f"2026-01-{day:02d}", 1) for day in range(1, 13)]
                                 + [row(f"2026-03-{day:02d}", 1) for day in range(1, 9)],
            "prompt_long_retouches": [row(f"2026-01-{day:02d}", 2) for day in range(1, 13)]
                                     + [row(f"2026-03-{day:02d}", -1) for day in range(1, 9)],
            "decisive_long_breakouts": [],
            "prompt_decisive_long_retouches": [],
        }
        result = _select(contexts, date(2026, 3, 1), minimum_training_trades=12, minimum_later_trades=8)
        self.assertEqual("prompt_long_retouches", result["selected_context"])
        self.assertFalse(result["later_data_passed"])


if __name__ == "__main__":
    unittest.main()

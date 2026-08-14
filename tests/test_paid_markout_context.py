from datetime import date
import unittest

from research.jobs.select_paid_markout_context import _read_path, choose_context


def row(day: str, result: float, side: str = "long", moment: str = "10:00") -> dict[str, object]:
    return {"signal_time": f"{day}T{moment}:00-05:00", "return_pct": result, "side": side}


class PaidMarkoutContextTests(unittest.TestCase):
    def test_reads_a_nested_markout_list(self):
        rows = [row("2026-01-02", 2)]
        self.assertEqual(rows, _read_path({"by_variant": {"base": rows}}, "by_variant.base"))

    def test_selection_is_made_on_earlier_dates_only(self):
        rows = (
            [row(f"2026-01-{day:02d}", 3, "long", "10:00") for day in range(1, 21)]
            + [row(f"2026-01-{day:02d}", -1, "short", "13:00") for day in range(1, 21)]
            + [row(f"2026-03-{day:02d}", 2, "long", "10:00") for day in range(1, 11)]
        )
        selected = choose_context(rows, date(2026, 3, 1), 20)
        self.assertEqual("long_all_day", selected["selected_context"])
        self.assertTrue(selected["later_passed"])


if __name__ == "__main__":
    unittest.main()

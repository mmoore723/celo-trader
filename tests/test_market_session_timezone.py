"""Regression guards for exchange-calendar-sensitive production code."""

from pathlib import Path
import unittest


class MarketSessionTimezoneTests(unittest.TestCase):
    def test_reconcile_uses_new_york_day_boundaries_across_dst(self) -> None:
        from api.routes.trades import _reconcile_day_bounds

        self.assertEqual(
            _reconcile_day_bounds("2026-01-15"),
            ("2026-01-15", "2026-01-15T05:00:00Z", "2026-01-16T05:00:00Z"),
        )
        self.assertEqual(
            _reconcile_day_bounds("2026-07-15"),
            ("2026-07-15", "2026-07-15T04:00:00Z", "2026-07-16T04:00:00Z"),
        )

    def test_session_sensitive_modules_do_not_use_server_calendar_date(self) -> None:
        root = Path(__file__).resolve().parents[1]
        modules = (
            "trading/controls/helpers.py",
            "trading/entry/contract.py",
            "trading/loop/audits.py",
            "trading/loop/inner.py",
            "trading/position_manager/close.py",
            "api/routes/settings.py",
            "api/routes/market.py",
        )

        offenders: list[str] = []
        for relative_path in modules:
            source = (root / relative_path).read_text(encoding="utf-8")
            if "date.today()" in source:
                offenders.append(relative_path)

        self.assertEqual(
            offenders,
            [],
            "Market-session logic must use trading.state._now_et(), not the "
            f"server's local calendar date: {offenders}",
        )


if __name__ == "__main__":
    unittest.main()

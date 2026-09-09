"""Regression guards for exchange-calendar-sensitive production code."""

from pathlib import Path
import unittest


class MarketSessionTimezoneTests(unittest.TestCase):
    def test_alpaca_daily_bar_uses_new_york_trading_date(self) -> None:
        from datetime import datetime, timezone
        from api.routes.trades import _alpaca_portfolio_timestamp_to_trading_date

        midnight_utc = int(datetime(2026, 8, 29, tzinfo=timezone.utc).timestamp())
        noon_utc = int(datetime(2026, 8, 29, 12, tzinfo=timezone.utc).timestamp())

        self.assertEqual(
            "2026-08-28",
            _alpaca_portfolio_timestamp_to_trading_date(midnight_utc),
        )
        self.assertEqual(
            "2026-08-29",
            _alpaca_portfolio_timestamp_to_trading_date(noon_utc),
        )

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
            "scanner/strategy_premarket.py",
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

    def test_premarket_does_not_shadow_the_new_york_clock(self) -> None:
        root = Path(__file__).resolve().parents[1]
        source = (root / "api/routes/market.py").read_text(encoding="utf-8")
        self.assertNotIn("_now_et   =", source)
        self.assertNotIn("_now_et =", source)


if __name__ == "__main__":
    unittest.main()

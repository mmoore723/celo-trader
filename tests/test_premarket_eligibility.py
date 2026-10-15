import json
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pandas as pd

from scanner import premarket_eligibility as screen


def evidence(**kwargs):
    return dict(rvol=2., premarket_volume_feed="tradier_consolidated", gap_pct=.5,
                hourly_direction="bullish", ema15_direction="bullish", atr10_pass=True, **kwargs)


class PolicyTests(unittest.TestCase):
    def test_all_18_boundaries_and_directions(self):
        self.assertEqual(len(screen.RULES), 18)
        for sid, (minimum, kind, floor) in screen.RULES.items():
            for direction in ("bullish", "bearish"):
                with self.subTest(sid=sid, direction=direction):
                    data = evidence()
                    data.update(rvol=minimum, hourly_direction=direction, ema15_direction=direction,
                                gap_pct=.5 if direction == "bullish" else -.5)
                    self.assertTrue(screen.evaluate(sid, "SPY", direction, data)["allowed"])
                    data["rvol"] = minimum - .00001
                    self.assertFalse(screen.evaluate(sid, "SPY", direction, data)["allowed"])

    def test_no_global_gap_floor_or_cap(self):
        for sid, (_, kind, floor) in screen.RULES.items():
            if not floor:
                data = evidence()
                for gap in (0, .001, 40, -40):
                    data["gap_pct"] = gap
                    self.assertTrue(screen.evaluate(sid, "SPY", "bullish", data)["allowed"], sid)

    def test_opening_momentum_floor_and_direction(self):
        sid = "V2_OPENING_MOMENTUM_RTH_EXPLORATORY"
        for ticker, minimum in (("SPY", .1), ("QQQ", .1), ("AAPL", .3)):
            data = evidence()
            data["gap_pct"] = minimum
            self.assertTrue(screen.evaluate(sid, ticker, "bullish", data)["allowed"])
            data["gap_pct"] = minimum - .0001
            self.assertFalse(screen.evaluate(sid, ticker, "bullish", data)["allowed"])
            data["gap_pct"] = -minimum
            self.assertFalse(screen.evaluate(sid, ticker, "bullish", data)["allowed"])

    def test_gap_fill_floor_but_no_fade_assumption(self):
        data = evidence()
        for gap, expected in ((.2, True), (-.2, True), (.199, False), (50, True)):
            data["gap_pct"] = gap
            self.assertEqual(expected, screen.evaluate("V2_GAP_FILL_RTH", "SPY", "bullish", data)["allowed"])

    def test_context_and_priority_do_not_veto_reversals(self):
        data = evidence()
        data["hourly_direction"] = "bearish"
        for sid, (_, kind, _) in screen.RULES.items():
            if kind in {"context", "priority"}:
                self.assertTrue(screen.evaluate(sid, "SPY", "bullish", data)["allowed"])
            elif kind in {"hourly", "gap_hourly"}:
                self.assertFalse(screen.evaluate(sid, "SPY", "bullish", data)["allowed"])

    def test_bad_volume_missing_context_and_untouched_strategies(self):
        for volume in (None, float("nan"), float("inf")):
            data = evidence()
            data["rvol"] = volume
            self.assertFalse(screen.evaluate("V2_TREND_CONT", "SPY", "bullish", data)["allowed"])
        data = evidence()
        data["premarket_volume_feed"] = "iex"
        self.assertFalse(screen.evaluate("V2_TREND_CONT", "SPY", "bullish", data)["allowed"])
        self.assertTrue(screen.evaluate("V2_SPY_TREND_CONT", "SPY", "bullish", {})["allowed"])
        data = evidence()
        data["atr10_pass"] = False
        self.assertFalse(screen.evaluate("RESEARCH_CTX_ORB_ATR10_V2", "SPY", "bullish", data)["allowed"])

    def test_scoped_persistent_cache_and_reopen_at_930(self):
        with TemporaryDirectory() as temp, patch("config.paths.get_user_data_dir", return_value=Path(temp)), \
             patch.object(screen, "matched_premarket_rvol", return_value={"SPY": {
                 "rvol": 1.5, "premarket_close": 101, "premarket_volume_feed": "tradier_consolidated"}}) as volume, \
             patch.object(screen, "_daily", return_value={"prior_close": 100}), \
             patch.object(screen, "_context", return_value={}):
            now = datetime(2026, 10, 15, 9)
            data = screen.evidence_for(None, "SPY", now, "context")
            self.assertAlmostEqual(data["gap_pct"], 1.)
            screen._cache.clear()
            screen.evidence_for(None, "SPY", now + timedelta(minutes=1), "context")
            screen.evidence_for(None, "SPY", now.replace(hour=10), "context")
            screen.evidence_for(None, "SPY", now.replace(hour=14), "context")
            self.assertEqual(volume.call_count, 3)
            self.assertEqual(json.loads(next(Path(temp).rglob("*.json")).read_text())["bucket"], "09:30")

    def test_15m_context_ignores_today_and_uses_actual_ema_structure(self):
        rows = []
        for day in pd.bdate_range("2026-09-01", "2026-10-15"):
            for i in range(26):
                price = 100 + len(rows) / 100
                rows.append(dict(time=day + pd.Timedelta(hours=9, minutes=30 + i * 15),
                                 open=price, high=price+1, low=price-1, close=price, volume=100))
        with patch.object(screen, "_frame", return_value=pd.DataFrame(rows)):
            result = screen._context(None, "SPY", datetime(2026,10,15,14), "ema15")
        self.assertEqual(result["ema15_direction"], "bullish")
        self.assertTrue(result["ema15_bar"].startswith("2026-10-14"))

    def test_screen_metadata_is_attached_without_mutating_exit_fields(self):
        sig = SimpleNamespace(strategy_id="V2_TREND_CONT", direction="bullish", meta={"stop_price": 99})
        with patch.object(screen, "evidence_for", return_value=evidence()):
            self.assertTrue(screen.screen_signal(None, "SPY", sig))
        self.assertEqual(sig.meta["stop_price"], 99)
        self.assertEqual(sig.meta["premarket_screen"]["policy"], screen.POLICY)

    def test_optional_context_failure_does_not_become_a_new_veto(self):
        data = evidence()
        data.pop("hourly_direction")
        data["higher_timeframe_error"] = "offline"
        self.assertTrue(screen.evaluate("V2_AFTERNOON_REVERSAL", "QQQ", "bearish", data)["allowed"])
        self.assertFalse(screen.evaluate("V2_TREND_CONT", "QQQ", "bearish", data)["allowed"])

    def test_matched_volume_uses_last_closed_minute_for_gap_levels(self):
        from tests.test_premarket_volume import Feed, ConsolidatedFeed
        from scanner.premarket_volume import matched_premarket_rvol
        provider = ConsolidatedFeed()
        raw = provider._get("", {})
        for row in raw["series"]["data"]:
            row.update(open=100, high=102, low=99, close=101)
        raw["series"]["data"].append(dict(time="2026-10-15T08:30:00", volume=999999,
                                           open=999, high=999, low=999, close=999))
        with patch.object(provider, "_get", return_value=raw):
            data = matched_premarket_rvol(Feed(), ["SPY"], datetime(2026,10,15,8,30), tradier=provider)["SPY"]
        self.assertEqual(data["premarket_close"], 101)
        self.assertEqual(data["premarket_high"], 102)
        self.assertEqual(data["premarket_low"], 99)
        self.assertEqual(data["premarket_volume"], 150)

    def test_daily_context_excludes_current_day(self):
        frame = pd.DataFrame([dict(time=pd.Timestamp("2026-10-14"), open=100, high=101, low=99, close=100, volume=100),
                              dict(time=pd.Timestamp("2026-10-15"), open=100, high=999, low=1, close=999, volume=999)])
        with patch.object(screen, "_frame", return_value=frame):
            data = screen._daily(None, "SPY", datetime(2026,10,15,14))
        self.assertEqual(data["prior_close"], 100)
        self.assertEqual(data["prior_session"], "2026-10-14")

    def test_hourly_requires_complete_930_anchored_hours(self):
        rows = []
        for day in pd.bdate_range("2026-10-05", "2026-10-15"):
            for i in range(78):
                price = 100 + len(rows) / 100
                rows.append(dict(time=day + pd.Timedelta(hours=9, minutes=30 + i * 5),
                                 open=price, high=price+1, low=price-1, close=price, volume=100))
        with patch.object(screen, "_frame", return_value=pd.DataFrame(rows)):
            data = screen._context(None, "SPY", datetime(2026,10,15,14), "hourly")
        self.assertEqual(data["hourly_bar"], "2026-10-14T14:30:00")
        self.assertEqual(data["hourly_direction"], "bullish")

    def test_router_filters_before_selection_but_observes_rejected(self):
        import strategy_router.route as router
        sid1, sid2 = "V2_SPY_TREND_CONT", "V2_SPY_AFTERNOON_FVG"
        a = SimpleNamespace(strategy_id=sid1, direction="bullish", confidence=.9, meta={}, rvol=2, trigger_bar="test")
        b = SimpleNamespace(strategy_id=sid2, direction="bullish", confidence=.8, meta={}, rvol=2, trigger_bar="test")
        frame = pd.DataFrame({"close": [100.,101.]})
        seen = []
        with patch.object(router, "ACTIVE_STRATEGIES", []), \
             patch.object(router, "_authorized_for_order", return_value=True), \
             patch.object(router, "compute_adx", return_value=30), \
             patch.object(router, "uses_reviewed_paid_execution_profile", return_value=True), \
             patch("shadow_ledger.resolve_due_directional_outcomes"):
            result = router.route_signals(frame, "SPY", enabled_strategies={sid1,sid2},
                prepared_today=frame, injected_signals=[a,b], quiet=True,
                preserve_reviewed_paid_rules=True, candidate_observer=lambda t,s,p:seen.append(s),
                premarket_screen=lambda t,s:s is b)
        self.assertEqual(result, [b])
        self.assertEqual(seen, [a,b])

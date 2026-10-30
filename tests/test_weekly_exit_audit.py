import hashlib
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from strategy_health.weekly_exit_audit.engine import audit
from strategy_health.weekly_exit_audit.replay import replay
from strategy_health.weekly_exit_audit.source import load, journal_time, recorded_hold
from strategy_health.weekly_exit_audit.statistics import noise
from strategy_health.weekly_exit_audit.store import read, save


def trade(identifier=1):
    start = datetime(2026, 1, 1, 15, tzinfo=timezone.utc)+timedelta(days=identifier)
    return dict(id=identifier, entry_time=start.isoformat(), exit_time=(start+timedelta(minutes=5)).isoformat(),
                entry_price=2., quantity=1, fees=3.3, realized_pnl=16.7,
                deadline=(start+timedelta(minutes=5)).isoformat(), issues=[],
                entry_iv=.4, entry_delta=.5, entry_gamma=.02, underlying_path=[{"close": 100}],
                option_path=[dict(time=(start+timedelta(minutes=i+1)).isoformat(), bid=bid, ask=bid+.05)
                             for i, bid in enumerate([2.7, 2.455, 2.4, 2.3, 2.2, 2.1])])


class WeeklyAuditTests(unittest.TestCase):
    def test_hold_comes_from_frozen_plan_not_current_strategy_defaults(self):
        meta = {"manual_plan": {"exit_plan": {"strategy_id": "SPY_TREND",
                "summary": "Hold the same selected contract for 30 minutes, then exit at the executable bid."}}}
        self.assertEqual(recorded_hold({}, meta, "SPY_TREND"), 30)
        self.assertIsNone(recorded_hold({}, meta, "OTHER"))
        self.assertIsNone(recorded_hold({}, {}, "SPY_TREND"))
        self.assertEqual(recorded_hold({"reviewed_exit_minutes": 45}, meta, "SPY_TREND"), 45)

    def test_journal_timezone_contract_is_eastern_not_utc(self):
        self.assertEqual(journal_time("2026-10-14T10:03:52"), "2026-10-14T10:03:52-04:00")
        self.assertEqual(journal_time("2026-12-14T10:03:52"), "2026-12-14T10:03:52-05:00")
        self.assertEqual(journal_time("2026-10-14T14:03:52Z"), "2026-10-14T10:03:52-04:00")

    def test_strict_boundary_and_next_quote(self):
        result = replay(trade())
        self.assertEqual(result["status"], "priced")
        self.assertAlmostEqual(result["net"], 26.7)
        self.assertEqual(result["decision"], trade()["option_path"][2]["time"])
        self.assertEqual(result["fill_time"], trade()["option_path"][3]["time"])

    def test_quantity_does_not_change_activation(self):
        source = trade()
        source["quantity"] = 3
        source["fees"] = 9.9
        self.assertEqual(replay(source)["decision"], replay(trade())["decision"])
        self.assertAlmostEqual(replay(source)["net"], 80.1)

    def test_missing_future_quotes_not_imputed(self):
        source = trade()
        source["option_path"] = source["option_path"][:1]
        self.assertEqual(replay(source)["status"], "capture_ends_before_exit")

    def test_gap_is_not_ignored(self):
        source = trade()
        source["option_path"] = source["option_path"][3:]
        self.assertEqual(replay(source)["status"], "price_gap")

    def test_audit_grid_and_small_sample_no_proposal(self):
        result = audit([trade(i) for i in range(3)])
        self.assertEqual(result["grid_combinations"], 936)
        self.assertEqual(len(result["grid"]), 936)
        self.assertEqual(result["recommendation"], "KEEP BASELINE")
        self.assertEqual(len(result["alternatives"]), 3)

    def test_missing_version_deadline_fails_closed(self):
        source = trade()
        source["deadline"] = None
        result = audit([source])
        self.assertEqual(result["status"], "INCOMPLETE")
        self.assertIsNone(result["baseline"])

    def test_noise_pairing_and_multiplicity(self):
        values = [10, -10, 20, -5, 30, 0]
        self.assertFalse(noise(values, values)["exceeds_noise"])
        low = noise(values, [0]*6, 1)
        high = noise(values, [0]*6, 939)
        self.assertGreater(high["total_noise_threshold"], low["total_noise_threshold"])

    def test_missing_timezone_preserves_coverage_and_recorded_results(self):
        source = trade()
        source["entry_time"] = "2026-01-02T15:00:00"
        result = audit([source])
        self.assertEqual(result["status"], "INCOMPLETE")
        self.assertIn("invalid_entry_timestamp_or_missing_timezone", result["coverage_issues"]["1"])
        self.assertAlmostEqual(result["actual_recorded"]["net"], 16.7)
        self.assertTrue(result["assumptions"])

    def test_store_account_mode_version_isolation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"audits.sqlite3"
            result = dict(status="COMPLETE", recommendation="KEEP BASELINE")
            ids = [save(path, key, result, []) for key in (
                ("a", "paper", "TSLA", "trend", "v1"), ("a", "paper", "TSLA", "trend", "v2"),
                ("b", "paper", "TSLA", "trend", "v1"), ("a", "live", "TSLA", "trend", "v1"))]
            self.assertEqual(len(read(path, "a", "paper")), 2)
            self.assertIsNone(read(path, "b", "paper", ids[0]))
            self.assertIsNone(read(path, "a", "live", ids[0]))
            self.assertEqual(read(path, "a", "paper", ids[1])["version"], "v2")

    def test_source_is_read_only_and_never_pools_versions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"trades.db"
            with sqlite3.connect(path) as conn:
                conn.execute("""CREATE TABLE trades(id INTEGER,ticker TEXT,strategy_id TEXT,
                    contract_symbol TEXT,broker_account_id TEXT,parent_trade_id INTEGER,status TEXT,
                    paper INTEGER,entry_time TEXT,exit_time TEXT,entry_price REAL,contracts INTEGER,
                    realized_pnl REAL,strategy_context_json TEXT)""")
                for i, version in enumerate(("v1", "v2", None), 1):
                    t = trade(i)
                    conn.execute("INSERT INTO trades VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                 (i, "TSLA", "trend", "TSLA260130C00100000", "a", None, "closed",
                                  1, "2026-10-14T10:00:00", "2026-10-14T10:30:01", 2, 1, 16.7,
                                  json.dumps({"strategy_version": version, "reviewed_exit_minutes": 30})))
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            buckets = load(path, "paper")
            self.assertEqual(len(buckets), 3)
            self.assertEqual({key[-1] for key in buckets}, {"v1", "v2", "UNKNOWN-TRADE-3"})
            for rows in buckets.values():
                self.assertEqual(rows[0]["deadline"], "2026-10-14T10:30:00-04:00")
                self.assertNotIn("invalid_price_or_timezone", rows[0]["issues"])
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)


if __name__ == "__main__":
    unittest.main()

from contextlib import contextmanager
from datetime import datetime
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from database.schema import _init_db_at
from database.research_exits import capture_authored_exits
from strategy_health.impulse_exit import STRATEGY_ID, PROTOCOL
from strategy_health.authored_exit_summary import load_authored_exits, authored_summary
from tests.test_impulse_exit_measurement import candles
from trading.tested_strategy_research import strategy_details
from trading.context_research_entries import evidence_version


class AuthoredExitCaptureTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name)/"test.db"
        _init_db_at(self.path)
        self.patch = patch("database.research_exits.get_conn", self.connect)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.now = datetime(2026, 9, 10, 10, 16)
        self.frame = candles()
        self.frame.loc[5, "low"] = 97
        self.quote = Mock(return_value=dict(symbol="XYZ", source_symbol="XYZ", bid=1.2, ask=1.3, bid_date="2026-09-10T10:15:30"))

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def seed(self, name="one", account="a", protocol=PROTOCOL, source="tradier_research_contract_v1", strategy_id=STRATEGY_ID, state=None):
        from config.strategy_catalog import REVIEWED_STRATEGIES
        spec = strategy_details(strategy_id) or REVIEWED_STRATEGIES[strategy_id]
        with self.connect() as conn:
            conn.execute("""INSERT INTO shadow_candidates
                (candidate_id,observed_at,trigger_bar,ticker,strategy_id,direction,confidence,broker_account_id,metadata_json)
                VALUES (?,'2026-09-10T10:05:01','2026-09-10T10:05','META',?,'bullish',.7,?,?)""",
                (name, strategy_id, account, json.dumps(dict(authored_exit_protocol=protocol, authored_exit_state=state,
                 underlying_stop=98, underlying_target=104,
                 strategy_version=evidence_version(strategy_id, spec.version)))))
            conn.execute("""INSERT INTO candidate_option_quote_observations
                (candidate_id,observed_at,observation_kind,contract_symbol,ask,bid,source)
                VALUES (?,'2026-09-10T10:05:03','entry','XYZ',2,1.9,?)""", (name, source))

    def capture(self, **changes):
        capture_authored_exits(**dict(account="a", bars_lookup=lambda _: self.frame,
                                    quote_lookup=self.quote, clock=lambda: self.now, **changes))

    def rows(self):
        with self.connect() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM research_strategy_exits ORDER BY candidate_id")]

    def test_same_contract_first_trigger_once_and_restart(self):
        self.seed()
        self.capture()
        before = self.rows()
        self.assertEqual("priced", before[0]["status"])
        self.assertEqual("2026-09-10T10:15:00", before[0]["decision_at"])
        self.frame.loc[5, "low"] = 99
        self.frame.loc[10, "high"] = 105
        self.now = datetime(2026, 9, 10, 10, 22)
        self.capture()
        self.assertEqual(before, self.rows())
        self.quote.assert_called_once_with("XYZ")

    def test_quote_failure_keeps_first_decision_then_expires(self):
        self.seed()
        self.quote.side_effect = RuntimeError("quote unavailable")
        self.capture()
        self.assertEqual("pending_quote", self.rows()[0]["status"])
        self.now = datetime(2026, 9, 10, 10, 21)
        self.capture()
        self.assertEqual("missing_quote", self.rows()[0]["status"])
        self.assertEqual("underlying_stop", self.rows()[0]["reason"])
        self.assertEqual(1, self.quote.call_count)

    def test_no_backfill_other_account_or_wrong_contract_profile(self):
        self.seed()
        self.seed("old", protocol=None)
        self.seed("other", account="b")
        self.seed("execution", source="execution")
        self.capture()
        self.assertEqual(["one"], [r["candidate_id"] for r in self.rows()])

    def test_all_overlapping_plays_recorded_with_one_shared_quote(self):
        for i in range(40):
            self.seed(str(i))
        self.capture()
        self.assertEqual(40, len(self.rows()))
        self.assertTrue(all(r["status"] == "priced" for r in self.rows()))
        self.assertEqual(1, self.quote.call_count)

    def test_missing_bars_and_stopped_pass_never_price(self):
        self.seed()
        self.capture(stopped=lambda: True)
        self.assertEqual([], self.rows())
        self.frame = self.frame.drop(index=5)
        self.now = datetime(2026, 9, 10, 10, 21)
        self.capture()
        self.assertEqual("unmeasurable", self.rows()[0]["status"])
        self.quote.assert_not_called()

    def test_summary_uses_only_selected_account_samples_and_after_cost_result(self):
        self.seed()
        self.seed("other", account="b")
        self.capture()
        with self.connect() as conn:
            exits = load_authored_exits(conn, "a", "2026-09-10")
        result = authored_summary([{"candidate_id": "one"}], exits)
        self.assertEqual(1, result["option_results"])
        self.assertEqual(0, result["profit_factor"])
        self.assertEqual(-83.3, result["net_one_contract_pnl"])
        self.assertEqual(-83.3, result["median_one_contract_pnl"])
        self.assertEqual(0, authored_summary([], exits)["option_results"])

    def test_migration_preserves_existing_data(self):
        self.seed()
        self.capture()
        before = self.rows()
        _init_db_at(self.path)
        self.assertEqual(before, self.rows())

    def test_supertrend_and_impulse_share_capture_without_mixing_protocol_results(self):
        from strategy_health.supertrend_exit import STRATEGY_ID as super_id, PROTOCOL as super_protocol
        from tests.test_supertrend_exit_measurement import seed
        self.seed()
        self.seed("super", strategy_id=super_id, protocol=super_protocol, state=seed())
        self.frame.loc[5:9, ["low", "close"]] = [96, 97]
        self.capture()
        exits = {r["candidate_id"]: r for r in self.rows()}
        self.assertEqual("underlying_stop", exits["one"]["reason"])
        self.assertEqual("opposite_flip", exits["super"]["reason"])
        self.assertEqual("priced", exits["super"]["status"])
        self.assertEqual(1, self.quote.call_count)
        samples = [{"candidate_id": name} for name in exits]
        self.assertEqual(1, authored_summary(samples, exits)["option_results"])
        self.assertEqual(1, authored_summary(samples, exits, super_protocol)["option_results"])

    def test_supertrend_missing_state_never_falls_back_to_dummy_stop(self):
        from strategy_health.supertrend_exit import STRATEGY_ID as super_id, PROTOCOL as super_protocol
        self.seed("super", strategy_id=super_id, protocol=super_protocol)
        self.capture()
        self.assertEqual("unmeasurable", self.rows()[0]["status"])
        self.assertEqual("missing_indicator_state", self.rows()[0]["reason"])
        self.quote.assert_not_called()

    def test_momentum_observation_prices_actual_bid_after_first_stop_minute(self):
        from strategy_health.momentum_exit import STRATEGY_ID as momentum_id, PROTOCOL as momentum_protocol
        from tests.test_momentum_exit_measurement import seed
        self.seed("momentum", strategy_id=momentum_id, protocol=momentum_protocol, state=seed())
        self.capture()
        row = self.rows()[0]
        self.assertEqual("atr_trailing_stop", row["reason"])
        self.assertEqual("2026-09-10T10:11:00", row["decision_at"])
        self.assertEqual("priced", row["status"])
        self.assertEqual(1.2, row["bid"])
        self.assertEqual(0, authored_summary([row], {"momentum": row})["option_results"])
        self.assertEqual(1, authored_summary([row], {"momentum": row}, momentum_protocol)["option_results"])

    def test_production_matrix_exposes_authored_sample_separately_from_timer(self):
        from strategy_health.research_matrix import build_research_matrix
        self.seed()
        self.capture()
        with patch("database.get_conn", self.connect), patch("database._now_et", return_value=self.now), patch(
            "config.get_settings", return_value={"active_broker_account_id": "a", "research_strategy_ids": [STRATEGY_ID]},
        ), patch("scanner.state_io._read_daily_universe", return_value={}):
            matrix = build_research_matrix()
        strategy = next(s for s in matrix["strategies"] if s["strategy_id"] == STRATEGY_ID)
        pair = next(p for p in strategy["pairs"] if p["ticker"] == "META")
        self.assertTrue(strategy["exit_measurement"]["authored_collector_enabled"])
        self.assertEqual(1, pair["option_results"])
        self.assertTrue(all(r['option_results'] == 0 for r in pair['exit_comparison']))
        self.assertEqual(1, pair["authored_exit_evidence"]["option_results"])
        self.assertEqual(-83.3, pair["authored_exit_evidence"]["net_one_contract_pnl"])

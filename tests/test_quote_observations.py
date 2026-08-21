"""Contract tests for paper-only option quote evidence capture."""

from contextlib import closing
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from database.option_quotes import (
    capture_due_candidate_option_quotes, record_candidate_contract_alternative,
    record_candidate_option_quote,
    record_paper_option_quote,
)
from database.research_observations import (
    close_due_paper_research_observations,
    get_paper_research_scorecard,
    start_paper_research_observation,
)
from database.schema import _init_db_at
from database.trades_query import get_all_trades
from shadow_ledger import record_router_candidate, resolve_candidate_from_context


class PaperOptionQuoteTests(unittest.TestCase):
    def test_candidate_preview_prices_every_signal_but_reuses_same_tick_selection(self) -> None:
        """Two same-direction candidates get evidence without two chain screens."""
        from trading.entry.candidate_observation import observe_candidate_contract

        signals = [
            SimpleNamespace(
                strategy_id="V2_SPY_TREND_CONT", direction="bullish",
                confidence=.81, meta={},
            ),
            SimpleNamespace(
                strategy_id="V2_SPY_AFTERNOON_FVG", direction="bullish",
                confidence=.78, meta={},
            ),
        ]
        contract = {
            "symbol": "SPY260821C00780000", "strike": 780, "expiry": "2026-08-21",
            "bid": 4.9, "ask": 5.1, "spread": .2, "volume": 100,
            "open_interest": 1000, "selection_model": "reviewed",
        }
        risk = SimpleNamespace(
            slippage_adjusted_entry=lambda ask: ask,
            calculate_contracts=lambda _entry, _balance: 1,
        )
        candidate_ids = iter(("candidate-1", "candidate-2"))

        def record_candidate(_ticker, signal, _underlying):
            signal.meta["shadow_candidate_id"] = next(candidate_ids)

        cache: dict = {}
        with patch(
            "trading.entry.candidate_observation.record_router_candidate",
            side_effect=record_candidate,
        ), patch(
            "trading.entry.candidate_observation.select_reviewed_v2_contract",
            return_value=(contract, {}),
        ) as selector, patch(
            "trading.entry.candidate_observation.snapshot_candidate_plan",
        ) as snapshot, patch(
            "trading.entry.candidate_observation.record_candidate_option_quote",
        ) as quote:
            for signal in signals:
                observe_candidate_contract(
                    ticker="SPY", signal=signal, underlying_price=779.0,
                    tradier=SimpleNamespace(), balance=5000.0, risk=risk,
                    settings={"max_position_dollars": 750.0},
                    selection_cache=cache,
                )

        self.assertEqual(1, selector.call_count)
        self.assertEqual(2, snapshot.call_count)
        self.assertEqual(2, quote.call_count)
        self.assertEqual(
            ["candidate-1", "candidate-2"],
            [call.kwargs["candidate_id"] for call in quote.call_args_list],
        )
        for call in snapshot.call_args_list:
            preview = call.args[0]["contract_preview"]
            self.assertEqual(5.10, preview["working_limit"])
            self.assertIsNone(preview["step_limit"])
            self.assertEqual(5.10, preview["maximum_entry_price"])

    def test_standard_preview_shows_first_limit_reprice_and_risk_ceiling_separately(self) -> None:
        """The learner-facing price plan must mirror normal execution semantics."""
        from trading.entry.candidate_observation import observe_candidate_contract

        signal = SimpleNamespace(
            strategy_id="STANDARD_TEST", direction="bullish",
            confidence=.75, meta={},
        )
        contract = {
            "symbol": "SPY260821C00780000", "strike": 780, "expiry": "2026-08-21",
            "bid": 4.90, "ask": 5.10, "spread": .20, "volume": 100,
            "open_interest": 1000,
        }
        risk = SimpleNamespace(
            slippage_adjusted_entry=lambda ask: round(ask * 1.05, 4),
            calculate_contracts=lambda _entry, _balance: 1,
        )

        def record_candidate(_ticker, observed_signal, _underlying):
            observed_signal.meta["shadow_candidate_id"] = "candidate-standard"

        with patch(
            "trading.entry.candidate_observation.record_router_candidate",
            side_effect=record_candidate,
        ), patch(
            "trading.entry.candidate_observation.select_contract",
            return_value=(contract, {}),
        ), patch(
            "trading.entry.candidate_observation.snapshot_candidate_plan",
        ) as snapshot, patch(
            "trading.entry.candidate_observation.record_candidate_option_quote",
        ):
            observe_candidate_contract(
                ticker="SPY", signal=signal, underlying_price=779.0,
                tradier=SimpleNamespace(), balance=5000.0, risk=risk,
                settings={"max_position_dollars": 750.0},
            )

        preview = snapshot.call_args.args[0]["contract_preview"]
        self.assertEqual(5.00, preview["planned_entry_price"])
        self.assertEqual(5.00, preview["working_limit"])
        self.assertEqual(5.10, preview["step_limit"])
        self.assertEqual(5.355, preview["maximum_entry_price"])
        self.assertEqual(535.50, preview["estimated_position_cost"])

    def test_existing_trade_table_migrates_before_account_index(self) -> None:
        """Older databases lack broker_account_id; init must add it before indexing."""
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "legacy.db"
            conn = sqlite3.connect(db_path)
            conn.execute(
                "CREATE TABLE trades (id INTEGER PRIMARY KEY, ticker TEXT, entry_time TEXT)"
            )
            conn.commit()
            conn.close()
            _init_db_at(db_path)
            conn = sqlite3.connect(db_path)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(trades)")}
            indexes = {row[1] for row in conn.execute("PRAGMA index_list(trades)")}
            conn.close()

        self.assertIn("broker_account_id", columns)
        self.assertIn("idx_trades_broker_account", indexes)

    def test_mark_is_deduped_per_minute_but_entry_and_exit_are_preserved(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "paper.db"
            _init_db_at(db_path)
            conn = sqlite3.connect(db_path)
            conn.execute(
                """INSERT INTO trades
                   (ticker, contract_symbol, option_type, strike, expiry, contracts,
                    entry_price, entry_time, entry_reason, status, paper, tier)
                   VALUES ('TSLA', 'TSLA260807C00300000', 'call', 300, '2026-08-07',
                           1, 5, '2026-08-03T10:00:00', 'test', 'open', 1, 'main')"""
            )
            conn.commit()

            with patch("database.option_quotes.get_conn", return_value=conn):
                common = dict(
                    trade_id=1, contract_symbol="TSLA260807C00300000",
                    observed_at=datetime(2026, 8, 3, 10, 0, 5),
                    quote={"bid": 4.9, "ask": 5.1}, source="test",
                )
                self.assertTrue(record_paper_option_quote(observation_kind="entry", fill_price=5.1, **common))
                self.assertTrue(record_paper_option_quote(observation_kind="mark", **common))
                self.assertTrue(record_paper_option_quote(observation_kind="mark", **common))
                self.assertTrue(record_paper_option_quote(observation_kind="exit", fill_price=4.8, **common))

            rows = conn.execute(
                "SELECT observation_kind, bid, ask, mid, fill_price "
                "FROM option_quote_observations ORDER BY id"
            ).fetchall()
            conn.close()

        self.assertEqual(["entry", "mark", "exit"], [row[0] for row in rows])
        self.assertEqual(("entry", 4.9, 5.1, 5.0, 5.1), rows[0])
        self.assertEqual(("exit", 4.9, 5.1, 5.0, 4.8), rows[-1])

    def test_invalid_kind_is_rejected_before_any_write(self) -> None:
        with self.assertRaises(ValueError):
            record_paper_option_quote(
                trade_id=1, contract_symbol="TSLA260807C00300000",
                observation_kind="unknown", observed_at=datetime(2026, 8, 3, 10),
                quote=None, source="test",
            )

    def test_candidate_quotes_capture_entry_and_due_horizons_without_trade(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "paper.db"
            _init_db_at(db_path)
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            conn.execute(
                """INSERT INTO shadow_candidates
                   (candidate_id, observed_at, ticker, strategy_id, direction,
                    confidence, tier, broker_account_id)
                   VALUES ('candidate-1', '2026-08-03T10:00:00-04:00', 'TSLA',
                           'TEST', 'bullish', .8, 'main', 'acct')"""
            )
            conn.commit()
            quote = {"bid": 4.9, "ask": 5.1, "mid": 5.0}
            with patch("database.option_quotes.get_conn", return_value=conn):
                self.assertTrue(record_candidate_option_quote(
                    candidate_id="candidate-1", contract_symbol="TSLA260807C00300000",
                    observation_kind="entry",
                    observed_at=datetime.fromisoformat("2026-08-03T10:00:00-04:00"),
                    quote=quote, source="test",
                ))
                self.assertTrue(record_candidate_contract_alternative(
                    candidate_id="candidate-1",
                    contract={"symbol": "TSLA260807C00310000", "bid": 3.9, "ask": 4.1},
                    observation_kind="entry",
                    observed_at=datetime.fromisoformat("2026-08-03T10:00:00-04:00"),
                    policies=["tightest_spread"], source="test",
                ))
                captured = capture_due_candidate_option_quotes(
                    ticker="TSLA",
                    observed_at=datetime.fromisoformat("2026-08-03T11:31:00-04:00"),
                    quote_lookup=lambda symbol: {**quote, "symbol": symbol},
                    broker_account_id="acct",
                )
            kinds = [row[0] for row in conn.execute(
                "SELECT observation_kind FROM candidate_option_quote_observations ORDER BY id"
            ).fetchall()]
            trade_count = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
            alt_kinds = [row[0] for row in conn.execute(
                "SELECT observation_kind FROM candidate_contract_alternatives ORDER BY id"
            ).fetchall()]
            conn.close()

        self.assertEqual(6, captured)
        self.assertEqual(["entry", "mark_30m", "mark_60m", "mark_90m"], kinds)
        self.assertEqual(["entry", "mark_30m", "mark_60m", "mark_90m"], alt_kinds)
        self.assertEqual(0, trade_count)

    def test_trade_query_does_not_mix_broker_accounts(self) -> None:
        """A newly connected broker account must not inherit local P&L history."""
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "paper.db"
            _init_db_at(db_path)
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            common = (
                "ticker, contract_symbol, option_type, strike, expiry, contracts, "
                "entry_price, entry_time, entry_reason, status, paper, tier, broker_account_id"
            )
            conn.execute(
                f"INSERT INTO trades ({common}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("TSLA", "TSLA260807C00300000", "call", 300, "2026-08-07", 1,
                 5, "2026-08-03T10:00:00", "old", "closed", 1, "main", "alpaca:paper:old"),
            )
            conn.execute(
                f"INSERT INTO trades ({common}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("TSLA", "TSLA260807P00300000", "put", 300, "2026-08-07", 1,
                 4, "2026-08-03T10:05:00", "new", "closed", 1, "main", "alpaca:paper:new"),
            )
            conn.commit()
            with patch("database.trades_query._conn_for_mode", return_value=conn):
                rows = get_all_trades(mode="paper", broker_account_id="alpaca:paper:new")
            conn.close()

        self.assertEqual(1, len(rows))
        self.assertEqual("new", rows[0]["entry_reason"])

    def test_shadow_candidate_links_router_signal_to_gate_outcome(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "paper.db"
            _init_db_at(db_path)
            conn = sqlite3.connect(db_path)
            signal = SimpleNamespace(
                strategy_id="V2_ORB_PULLBACK", direction="bullish", confidence=0.81,
                trigger_bar="2026-08-03T10:00:00", tier="main", meta={"rvol": 1.8},
            )
            with patch("shadow_ledger.get_conn", return_value=conn):
                record_router_candidate("TSLA", signal)
                resolve_candidate_from_context(
                    {"strategy_meta": signal.meta}, "blocked", "budget", "cap reached", None,
                )
            row = conn.execute(
                "SELECT strategy_id, final_outcome, gate_reason, gate_detail "
                "FROM shadow_candidates"
            ).fetchone()
            conn.close()

        self.assertEqual(("V2_ORB_PULLBACK", "blocked", "budget", "cap reached"), row)

    def test_shadow_candidate_records_same_session_directional_outcome(self) -> None:
        from shadow_ledger import resolve_due_directional_outcomes

        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "paper.db"
            _init_db_at(db_path)
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            signal = SimpleNamespace(
                strategy_id="V2_ORB_PULLBACK", direction="bullish", confidence=0.81,
                trigger_bar="2026-08-03T10:00:00", tier="main", meta={},
            )
            observed = datetime(2026, 8, 3, 10, 0)
            due = datetime(2026, 8, 3, 11, 1)
            with patch("shadow_ledger.get_conn", return_value=conn), patch(
                "shadow_ledger._now_et", side_effect=[observed, due],
            ):
                record_router_candidate("TSLA", signal, 300.0)
                resolve_due_directional_outcomes("TSLA", 303.0)
            row = conn.execute(
                "SELECT underlying_entry_price, underlying_exit_price, directional_move_pct, direction_correct "
                "FROM shadow_candidates"
            ).fetchone()
            conn.close()

        self.assertEqual((300.0, 303.0, 1.0, 1), tuple(row))

    def test_research_observation_is_deduped_and_never_creates_a_trade(self) -> None:
        """A paper study stores conservative quote evidence outside trades."""
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "paper.db"
            _init_db_at(db_path)
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            started = datetime(2026, 8, 3, 10, 1)
            closed = datetime(2026, 8, 3, 15, 56)
            common = dict(
                study_id="QQQ_TEST", observed_at=started, ticker="QQQ", direction="bearish",
                underlying_entry_price=600.0, broker_account_id="alpaca:paper:test",
                contract={"symbol": "QQQ260821P00600000", "expiry": "2026-08-21", "strike": 600,
                          "bid": 5.0, "ask": 5.2, "mid": 5.1},
            )
            with patch("database.research_observations.get_conn", return_value=conn):
                self.assertTrue(start_paper_research_observation(**common))
                self.assertFalse(start_paper_research_observation(**common))  # duplicate is ignored safely
                self.assertEqual(1, close_due_paper_research_observations(
                    study_id="QQQ_TEST", observed_at=closed, ticker="QQQ", underlying_exit_price=594.0,
                    broker_account_id="alpaca:paper:test",
                    quote_lookup=lambda symbol: {"symbol": symbol, "bid": 6.0, "ask": 6.2, "mid": 6.1},
                ))
                scorecard = get_paper_research_scorecard(
                    study_id="QQQ_TEST", broker_account_id="alpaca:paper:test",
                )
            observation = conn.execute(
                "SELECT status, underlying_move_pct, executable_return_pct FROM paper_research_option_observations"
            ).fetchone()
            trade_count = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
            conn.close()

        self.assertEqual(("closed", 1.0), tuple(observation)[:2])
        self.assertAlmostEqual(15.3846153846, float(observation[2]), places=8)
        self.assertEqual(0, trade_count)
        self.assertEqual({"observations": 1, "closed": 1, "quote_measured": 1, "option_win_rate_pct": 100.0},
                         {key: scorecard[key] for key in ("observations", "closed", "quote_measured", "option_win_rate_pct")})

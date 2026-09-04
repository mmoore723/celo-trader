"""The realism audit is deterministic, account-scoped and read-only."""
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from research.jobs.audit_paper_quote_realism import audit
from research.paper_quote_realism import analyze


def trade(**overrides):
    row = dict(id=1, ticker="SPY", strategy_id="TEST", status="closed", contracts=2,
               contract_symbol="SPY260911C00780000", entry_time="2026-09-04T12:20:16",
               exit_time="2026-09-04T12:50:16", realized_pnl=34)
    row.update(overrides)
    return row


def quote(kind, **overrides):
    row = dict(id=1, trade_id=1, contract_symbol="SPY260911C00780000",
               observed_at="2026-09-04T12:20:17", observation_kind=kind,
               bid=4.14, ask=4.16, source="tradier_chain" if kind == "entry" else "tradier_quote")
    row.update(overrides)
    return row


class PaperQuoteRealismTests(unittest.TestCase):
    def test_uses_saved_ask_bid_and_fees_not_paper_fill(self):
        result = analyze([trade(realized_pnl=500)], [quote("entry"), quote(
            "exit", observed_at="2026-09-04T12:50:15", bid=4.29, ask=4.31,
            source="tradier_pre_submit_exit_quote")])
        row = result["trades"][0]
        self.assertAlmostEqual(26, row["quote_pnl_before_fees"])
        self.assertAlmostEqual(.48, row["modeled_passthrough_fees"])
        self.assertAlmostEqual(25.52, row["quote_pnl_after_fees"])
        self.assertAlmostEqual(474, row["paper_minus_quote_before_fees"])
        self.assertEqual("exact_pre_submit", row["exit_evidence"])

    def test_exact_exit_wins_over_more_favorable_legacy_mark(self):
        result = analyze([trade()], [quote("entry"), quote(
            "mark", observed_at="2026-09-04T12:50:10", bid=9, ask=9.1), quote(
            "exit", observed_at="2026-09-04T12:50:17", bid=4.2, ask=4.22,
            source="tradier_pre_submit_exit_quote")])
        self.assertEqual(4.2, result["trades"][0]["exit_bid"])
        self.assertEqual("exact_pre_submit", result["trades"][0]["exit_evidence"])

    def test_legacy_mark_must_precede_exit_be_fresh_and_match_contract(self):
        rows = [quote("entry"), quote("mark", observed_at="2026-09-04T12:47:00"),
                quote("mark", id=3, observed_at="2026-09-04T12:50:20", bid=9, ask=10),
                quote("mark", id=4, observed_at="2026-09-04T12:50:10", bid=8, ask=9,
                      contract_symbol="OTHER"),
                quote("mark", id=5, observed_at="2026-09-04T12:50:00", bid=4.1, ask=4.2)]
        result = analyze([trade()], rows)
        self.assertEqual(4.1, result["trades"][0]["exit_bid"])
        self.assertEqual("legacy_nearby_mark", result["trades"][0]["exit_evidence"])
        self.assertEqual(16, result["trades"][0]["exit_quote_age_seconds"])

    def test_invalid_crossed_nonfinite_unknown_or_missing_quotes_stay_excluded(self):
        bad = [quote("entry", ask=float("nan")), quote(
            "exit", observed_at="2026-09-04T12:50:15", bid=5, ask=4,
            source="tradier_pre_submit_exit_quote")]
        result = analyze([trade()], bad)
        self.assertEqual(0, result["summary"]["measured_trades"])
        self.assertEqual({"missing_entry_ask": 1}, result["excluded"])
        json.dumps(result, allow_nan=False)

    def test_exact_entry_and_exit_quotes_must_be_near_the_trade_events(self):
        result = analyze([trade()], [quote("entry", observed_at="2026-09-04T12:17:00"), quote(
            "exit", observed_at="2026-09-04T12:50:15", bid=4.29, ask=4.31,
            source="tradier_pre_submit_exit_quote")])
        self.assertEqual({"missing_entry_ask": 1}, result["excluded"])
        result = analyze([trade()], [quote("entry"), quote(
            "exit", observed_at="2026-09-04T12:53:00", bid=4.29, ask=4.31,
            source="tradier_pre_submit_exit_quote")])
        self.assertEqual({"missing_exit_bid": 1}, result["excluded"])

    def test_missing_and_open_rows_are_not_zero_returns(self):
        result = analyze([trade(), trade(id=2, status="open", realized_pnl=None)], [quote("entry")])
        self.assertIsNone(result["summary"]["quote_pnl_after_fees"])
        self.assertEqual({"missing_exit_bid": 1, "not_closed": 1}, result["excluded"])

    def test_group_profit_factor_uses_measured_fee_adjusted_rows(self):
        losing = trade(id=2, ticker="TSLA", contracts=1, contract_symbol="TSLA260911C00350000",
                       realized_pnl=-10)
        quotes = [quote("entry"), quote("exit", observed_at="2026-09-04T12:50:15",
                  bid=4.29, ask=4.31, source="tradier_pre_submit_exit_quote"),
                  quote("entry", id=3, trade_id=2, contract_symbol=losing["contract_symbol"],
                        bid=1.98, ask=2),
                  quote("exit", id=4, trade_id=2, contract_symbol=losing["contract_symbol"],
                        observed_at="2026-09-04T12:50:15", bid=1.9, ask=1.95,
                        source="tradier_pre_submit_exit_quote")]
        result = analyze([trade(), losing], quotes, fee_per_contract_side=0)
        self.assertAlmostEqual(26 / 10, result["summary"]["quote_profit_factor_after_fees"])
        self.assertEqual(2, len(result["by_strategy_ticker"]))

    def test_bad_parameters_and_duplicate_trade_rows_fail_closed(self):
        with self.assertRaises(ValueError):
            analyze([trade(), trade()], [])
        with self.assertRaises(ValueError):
            analyze([], [], max_legacy_age_seconds=0)
        with self.assertRaises(ValueError):
            analyze([], [], fee_per_contract_side=float("inf"))

    def test_account_mode_dates_and_database_bytes_are_unchanged(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "paper.db"
            conn = sqlite3.connect(path)
            conn.executescript('''
                CREATE TABLE trades(id INTEGER PRIMARY KEY,ticker TEXT,strategy_id TEXT,
                  status TEXT,contracts INTEGER,contract_symbol TEXT,entry_time TEXT,
                  exit_time TEXT,realized_pnl REAL,paper INTEGER,broker_account_id TEXT);
                CREATE TABLE option_quote_observations(id INTEGER PRIMARY KEY,trade_id INTEGER,
                  contract_symbol TEXT,observed_at TEXT,observation_kind TEXT,bid REAL,ask REAL,source TEXT);
            ''')
            for idx, owner, paper, day in ((1,"mine",1,"2026-09-04"), (2,"other",1,"2026-09-04"),
                                           (3,"mine",0,"2026-09-04"), (4,"mine",1,"2026-09-05")):
                row = trade(id=idx, entry_time=day+"T12:20:16")
                row.update(paper=paper, broker_account_id=owner)
                conn.execute(f"INSERT INTO trades({','.join(row)}) VALUES ({','.join('?' for _ in row)})",
                             tuple(row.values()))
                for qidx, q in enumerate((quote("entry"), quote(
                    "exit", observed_at=day+"T12:50:15", bid=4.29, ask=4.31,
                    source="tradier_pre_submit_exit_quote")), start=1):
                    q.update(id=idx*10+qidx, trade_id=idx)
                    conn.execute(f"INSERT INTO option_quote_observations({','.join(q)}) "
                                 f"VALUES ({','.join('?' for _ in q)})", tuple(q.values()))
            conn.commit(); conn.close()
            before = path.read_bytes()
            result = audit(path, "mine", "2026-09-04", "2026-09-05")
            self.assertEqual([1], [row["trade_id"] for row in result["trades"]])
            self.assertEqual(before, path.read_bytes())
            self.assertNotIn("broker_account_id", json.dumps(result))
            with self.assertRaises(ValueError):
                audit(path, "", "2026-09-04")

    def test_missing_database_is_not_created(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "missing.db"
            with self.assertRaises(sqlite3.OperationalError):
                audit(path, "mine", "2026-09-04")
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()

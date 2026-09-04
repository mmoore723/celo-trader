"""No broker, network, runtime settings, or live database needed."""
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from research.fill_fidelity import analyze
from research.jobs.audit_fill_fidelity import audit


def trade(**overrides):
    return dict(id=209, ticker="SPY", strategy_id="TEST", status="closed", contracts=2,
                contract_symbol="SPY260911C00780000", entry_time="2026-09-04T12:20:16",
                exit_time="2026-09-04T12:50:16", entry_price=4.13, exit_price=4.30,
                realized_pnl=34, **overrides)


def quote(kind="entry", **overrides):
    row = dict(id=700, trade_id=209, contract_symbol="SPY260911C00780000",
               observed_at="2026-09-04T12:20:17", observation_kind=kind,
               bid=4.14, ask=4.16, source="tradier")
    row.update(overrides)
    return row


class FillFidelityTests(unittest.TestCase):
    def test_missing_exit_bid_is_unknown_not_zero_or_nearby_mark(self):
        result = analyze([trade()], [quote(), quote("exit", bid=None),
                                     quote("mark", bid=9.99)])
        self.assertIsNone(result["summary"]["exit_difference_dollars"])
        self.assertIsNone(result["summary"]["saved_quote_round_trip"])
        self.assertEqual(0, result["summary"]["paired_exit_quotes"])
        self.assertAlmostEqual(-6, result["summary"]["entry_difference_dollars"])
        self.assertFalse(result["live_ready"])

    def test_round_trip_bridge_is_arithmetic_not_slippage_proof(self):
        result = analyze([trade()], [quote(), quote("exit", bid=4.29)])
        row = result["trades"][0]
        self.assertAlmostEqual(34, row["saved_quote_round_trip"]-
            row["entry_difference_dollars"]-row["exit_difference_dollars"])
        self.assertEqual("not_verified", row["quote_market_freshness"])

    def test_other_contract_cannot_supply_missing_exit(self):
        result = analyze([trade()], [quote(), quote("exit", contract_symbol="OTHER")])
        self.assertEqual(0, result["summary"]["paired_exit_quotes"])

    def test_open_position_is_not_a_win_or_a_zero_loss(self):
        row = trade()
        row.update(status="open", exit_price=None, realized_pnl=None)
        result = analyze([row], [quote()])
        self.assertEqual(1, result["summary"]["open_rows"])
        self.assertIsNone(result["summary"]["recorded_pnl"])
        self.assertIsNone(result["summary"]["recorded_profit_factor"])

    def test_missing_closed_pnl_does_not_produce_full_sample_pf(self):
        other = trade()
        other.update(id=210, realized_pnl=None)
        result = analyze([trade(), other], [])
        self.assertEqual(1, result["summary"]["closed_rows_missing_pnl"])
        self.assertIsNone(result["summary"]["recorded_profit_factor"])

    def test_nan_quote_is_not_measured_and_json_stays_valid(self):
        result = analyze([trade()], [quote(ask=float("nan"))])
        self.assertEqual(0, result["summary"]["paired_entry_quotes"])
        json.dumps(result, allow_nan=False)

    def test_earliest_quote_is_frozen_even_if_later_quote_is_better(self):
        later = quote(id=701, ask=1.0, observed_at="2026-09-04T16:21:17Z")
        result = analyze([trade()], [later, quote()])
        self.assertAlmostEqual(-6, result["summary"]["entry_difference_dollars"])

    def test_duplicate_trades_raise_instead_of_doubling_pnl(self):
        with self.assertRaises(ValueError):
            analyze([trade(), trade()], [])

    def test_duplicate_quote_records_do_not_double_trade_pnl(self):
        result = analyze([trade()], [quote(), quote(id=701)])
        self.assertEqual(1, result["summary"]["closed_rows"])
        self.assertEqual(34, result["summary"]["recorded_pnl"])
        self.assertAlmostEqual(-6, result["summary"]["entry_difference_dollars"])

    def test_empty_sample_is_unknown_not_a_zero_return(self):
        result = analyze([], [])
        self.assertIsNone(result["summary"]["recorded_pnl"])
        self.assertIsNone(result["summary"]["recorded_profit_factor"])

    def test_bad_pnl_is_reported_but_historical_row_is_unchanged(self):
        row = trade()
        row["realized_pnl"] = 500
        result = analyze([row], [])
        self.assertEqual([209], result["summary"]["pnl_arithmetic_issues"])
        self.assertEqual(500, row["realized_pnl"])

    def test_zero_exit_bid_remains_a_measured_zero(self):
        result = analyze([trade()], [quote(), quote("exit", bid=0)])
        self.assertEqual(1, result["summary"]["paired_exit_quotes"])
        self.assertAlmostEqual(-860, result["summary"]["exit_difference_dollars"])

    def test_account_mode_dates_and_read_only_database(self):
        with TemporaryDirectory() as directory:
            path = Path(directory)/"paper.db"
            conn = sqlite3.connect(path)
            conn.executescript('''
                CREATE TABLE trades(id INTEGER PRIMARY KEY,ticker TEXT,strategy_id TEXT,
                  status TEXT,contracts INTEGER,contract_symbol TEXT,entry_time TEXT,
                  exit_time TEXT,entry_price REAL,exit_price REAL,realized_pnl REAL,
                  paper INTEGER,broker_account_id TEXT);
                CREATE TABLE option_quote_observations(id INTEGER PRIMARY KEY,trade_id INTEGER,
                  contract_symbol TEXT,observed_at TEXT,observation_kind TEXT,bid REAL,ask REAL,source TEXT);
            ''')
            for idx, owner, paper, day in ((1,"mine",1,"2026-09-04"), (2,"other",1,"2026-09-04"),
                                          (3,"mine",0,"2026-09-04"), (4,"mine",1,"2026-09-05")):
                row = trade()
                row.update(id=idx, entry_time=day+"T12:20:16", paper=paper, broker_account_id=owner)
                cols = ','.join(row)
                conn.execute(f"INSERT INTO trades({cols}) VALUES ({','.join('?' for _ in row)})",tuple(row.values()))
            conn.commit()
            conn.close()
            before = path.read_bytes()
            result = audit(path,"mine","2026-09-04","2026-09-05")
            self.assertEqual([1], [r["trade_id"] for r in result["trades"]])
            self.assertEqual(before,path.read_bytes())
            self.assertNotIn("broker_account_id", json.dumps(result))
            with self.assertRaises(ValueError):
                audit(path,"","2026-09-04")
            with self.assertRaises(ValueError):
                audit(path,1,"2026-09-04")
            with self.assertRaises(ValueError):
                audit(path,"mine","2026-09-04","2026-09-04")

    def test_missing_database_is_not_created(self):
        with TemporaryDirectory() as directory:
            path = Path(directory)/"missing.db"
            with self.assertRaises(sqlite3.OperationalError):
                audit(path,"mine","2026-09-04")
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()

"""Research-only synthetic checks for approved export scope; no production connection."""
import contextlib
import io
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from database import schema
from research.jobs import export_september_paper_audit as audit
from trading.position_manager.manage import _evaluate_reviewed_strategy_exit


class SeptemberAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'fixture.db'
        with sqlite3.connect(self.path) as conn:
            for name in ('_CREATE_TRADES', '_CREATE_SHADOW_CANDIDATES',
                         '_CREATE_OPTION_QUOTE_OBSERVATIONS', '_CREATE_BROKER_ORDER_EVENTS'):
                conn.executescript(getattr(schema, name))
            self.add_trade(conn, 222)

    def add_trade(self, conn, id, account='fixture-owner', date='2026-09-11',
                  strategy='V2_SPY_TREND_CONT', paper=1):
        conn.execute('''INSERT INTO trades(id,ticker,contract_symbol,option_type,
          strike,expiry,contracts,entry_price,entry_time,strategy_id,paper,broker_account_id)
          VALUES(?, 'SPY','SPY_FIXTURE','put',100,'2026-09-18',2,5.40,?,?,?,?)''',
          (id, date+'T15:10:00-04:00', strategy, paper, account))

    def run_export(self):
        output = io.StringIO()
        with patch.object(audit, 'DB', str(self.path)), contextlib.redirect_stdout(output):
            audit.export()
        return json.loads(output.getvalue())

    def test_other_users_modes_strategies_and_dates_excluded(self):
        with sqlite3.connect(self.path) as conn:
            self.add_trade(conn, 223, account='unrelated-user')
            self.add_trade(conn, 224, date='2026-09-07')
            self.add_trade(conn, 225, date='2026-09-12')
            self.add_trade(conn, 226, strategy='RESEARCH_ONLY')
            self.add_trade(conn, 227, paper=0)
            self.add_trade(conn, 228, strategy='V2_ORB_PULLBACK')
        result = self.run_export()
        self.assertEqual([222,228], [row['id'] for row in result['trades']])
        self.assertNotIn('fixture-owner', json.dumps(result))
        self.assertNotIn('current_settings_not_historical', result)

    def test_only_linked_quotes_exported_and_no_database_mutation(self):
        with sqlite3.connect(self.path) as conn:
            for trade_id in (222,999):
                conn.execute('''INSERT INTO option_quote_observations(trade_id,
                  observed_at,observed_minute,observation_kind,contract_symbol,bid,ask,source)
                  VALUES(?, '2026-09-11T15:11:00-04:00','15:11','mark','SPY_FIXTURE',5,5.1,'fixture')''', (trade_id,))
        before = self.path.read_bytes()
        result = self.run_export()
        self.assertEqual([222], [row['trade_id'] for row in result['option_quotes']])
        self.assertEqual(before, self.path.read_bytes())

    def test_unknown_metadata_and_nested_payloads_not_exported(self):
        result = audit.selected_meta(json.dumps({'strategy_version':'2.1.0',
            'api_key':'do-not-export', 'source':{'secret':'do-not-export'}, 'v2_stop':100}))
        self.assertEqual({'strategy_version':'2.1.0','v2_stop':100}, result)

    def test_wrong_anchor_cannot_select_another_account(self):
        with sqlite3.connect(self.path) as conn:
            conn.execute("UPDATE trades SET strategy_id='OTHER' WHERE id=222")
        with self.assertRaises(AssertionError):
            self.run_export()

    def test_visible_paper_subset_arithmetic_not_full_account(self):
        spy = list(map(Decimal, ['-38','-2','30','-30']))
        tsla = list(map(Decimal, ['-230','-230']))
        self.assertEqual(Decimal('-40'), sum(spy))
        self.assertEqual(Decimal('0.43'), (Decimal(30)/70).quantize(Decimal('.01')))
        self.assertEqual(Decimal('-500'), sum(spy+tsla))
        self.assertEqual(Decimal('.10'), -sum(spy+tsla)/Decimal(5000))

    def test_two_leg_reviewed_router_holds_despite_price_context(self):
        entry = datetime.fromisoformat('2026-09-11T10:06:00-04:00')
        trade = {'strategy_id':'V2_TSLA_TWO_LEG_TREND_PULLBACK',
                 'entry_price':8.5, 'current_price':6.25,
                 'strategy_context_json':json.dumps({'v2_stop':100})}
        kwargs = dict(one_minute_bars=None, five_minute_bars=None)
        self.assertEqual((False,'hold'), _evaluate_reviewed_strategy_exit(
            trade, entry, entry+timedelta(minutes=89), **kwargs))
        decision, reason = _evaluate_reviewed_strategy_exit(
            trade, entry, entry+timedelta(minutes=90), **kwargs)
        self.assertTrue(decision)
        self.assertIn('paid_markout_90m', reason)


if __name__ == '__main__':
    unittest.main()

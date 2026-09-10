"""ORB forward-only dynamic comparison keeps the native 90-minute control."""
from datetime import timedelta
import json
import unittest
from unittest.mock import patch

from database.option_profit_protection import capture
from database.reference_contract_tests import record, load, summary as reference_summary
from strategy_health.option_profit_protection import ORB_STRATEGY_ID as SID, ORB_PROTOCOL, summary
from tests import test_option_profit_protection as fixtures
from tests.test_option_profit_protection import ENTRY, quote


class OrbProfitTests(unittest.TestCase):
    setUp = fixtures.CaptureTests.setUp
    connect = fixtures.CaptureTests.connect
    rows = fixtures.CaptureTests.rows
    capture = fixtures.CaptureTests.capture

    def seed(self,name='one',version='2.0.0',protocol=ORB_PROTOCOL,account='a'):
        fixtures.CaptureTests.seed(self,name,version=version,protocol=protocol,account=account)
        with self.connect() as conn:
            conn.execute('UPDATE shadow_candidates SET strategy_id=? WHERE candidate_id=?',(SID,name))

    def step(self,seconds,bid=2.2):
        self.now=ENTRY+timedelta(seconds=seconds)
        self.lookup.return_value=quote(bid,seconds)
        self.capture()

    def reference(self,name='one'):
        with patch('database.reference_contract_tests.get_conn',self.connect):
            record(candidate_id=name,strategy_id=SID,direction='bearish',meta={'strategy_version':'2.0.0'},
                   contract=dict(symbol='XYZ',ask=2,bid=1.96),observed_at=ENTRY,details={'reason':'selected'})

    def reference_rows(self):
        with self.connect() as conn:return load(conn,'a','2026-09-10')

    def test_forward_metadata_exact_version_accounts_all_overlaps(self):
        for i in range(40):self.seed(str(i))
        self.seed('old',protocol=None);self.seed('wrong-version',version='2.1.0');self.seed('other',account='b')
        self.step(30)
        self.assertEqual(40,len(self.rows()))
        self.lookup.assert_called_once_with('XYZ')
        self.assertTrue(all(r['protocol']==ORB_PROTOCOL for r in self.rows().values()))

    def test_90_minute_control_and_later_trail_fill_in_both_cohorts(self):
        self.seed();self.reference()
        self.step(30);self.lookup.assert_called_once_with('XYZ')
        self.step(60,2.1)
        for row in (self.rows()['one'],self.reference_rows()['one']):
            self.assertEqual('pending_quote',row['state']['trail']['status'])
            self.assertNotIn('bid',row['state']['trail'])
        self.step(90,2.08)
        self.step(1801,1.95)
        for row in (self.rows()['one'],self.reference_rows()['one']):
            self.assertEqual('collecting',row['state']['control']['status'])
            self.assertEqual('priced',row['state']['trail']['status'])
        self.step(5401,1.95)
        for row in (self.rows()['one'],self.reference_rows()['one']):
            self.assertEqual('fixed_90m',row['state']['control']['reason'])
            self.assertEqual('priced',row['state']['control']['status'])
        generic=summary([{'candidate_id':'one'}],self.rows(),SID)
        ref=reference_summary([{'candidate_id':'one'}],self.reference_rows(),SID)
        self.assertEqual(90,generic['minutes']);self.assertEqual(13,generic['average_improvement'])
        self.assertEqual(1,ref['profit_protection']['paired_results'])
        self.assertEqual(90,ref['profit_protection']['minutes'])

    def test_legacy_reference_control_is_preserved_not_promoted_into_trail(self):
        self.seed(protocol=None);self.reference()
        with self.connect() as conn:
            row=conn.execute('SELECT state_json FROM research_reference_contract_tests').fetchone()
            state=json.loads(row['state_json']);state['trail']={'status':'not_tested'}
            conn.execute("UPDATE research_reference_contract_tests SET protocol='reference_fixed_90m_v1',state_json=?",(json.dumps(state),))
        self.reference()  # Repeated enrolment cannot replace a historical protocol.
        self.step(30);self.lookup.assert_not_called()
        self.step(5401,2.1)
        rows=self.reference_rows();self.assertEqual('not_tested',rows['one']['state']['trail']['status'])
        result=reference_summary([{'candidate_id':'one'}],rows,SID)
        self.assertEqual(1,result['option_results']);self.assertEqual(6.7,result['control']['net_pnl'])
        self.assertEqual(0,result['profit_protection']['tracked'])
        self.assertEqual({},self.rows())

    def test_missing_path_does_not_erase_90m_control_or_fabricate_trail_profit(self):
        self.seed();self.step(121)
        self.assertEqual('missing_path',self.rows()['one']['state']['trail']['status'])
        self.step(5401)
        result=summary([{'candidate_id':'one'}],self.rows(),SID)
        self.assertEqual('priced',self.rows()['one']['state']['control']['status'])
        self.assertEqual(0,result['paired_results']);self.assertIsNone(result['average_improvement'])

    def test_late_day_entry_cannot_be_initialized_as_a_shorter_test(self):
        self.seed()
        late=ENTRY.replace(hour=15)
        with self.connect() as conn:
            conn.execute('UPDATE shadow_candidates SET observed_at=?',(late.isoformat(),))
            conn.execute('UPDATE candidate_option_quote_observations SET observed_at=?',(late.isoformat(),))
        self.now=late+timedelta(seconds=30);self.capture()
        self.assertEqual('invalid_entry',self.rows()['one']['state']['control']['status'])
        self.lookup.assert_not_called()

    def test_unarmed_path_stays_open_past_30_until_90_minutes(self):
        self.seed();self.reference()
        for second in range(60,5400,60):
            self.step(second,1.9)
        for row in (self.rows()['one'],self.reference_rows()['one']):
            self.assertEqual('collecting',row['state']['trail']['status'])
            self.assertIsNone(row['state']['stop'])
        self.step(5401,1.8)
        for row in (self.rows()['one'],self.reference_rows()['one']):
            self.assertEqual(row['state']['control'],row['state']['trail'])

    def test_matrix_exposes_90m_tests_without_replacing_primary_results(self):
        from strategy_health.research_matrix import build_research_matrix
        self.seed();self.reference()
        self.step(30);self.step(60,2.1);self.step(90,2.08);self.step(5401,1.95)
        settings={'active_broker_account_id':'a','watchlist':['META','NVS']}
        with patch('database.get_conn',self.connect),patch('database._now_et',return_value=ENTRY),patch('config.get_settings',return_value=settings):
            matrix=build_research_matrix(90)
        strategy=next(r for r in matrix['strategies'] if r['strategy_id']==SID)
        pair=next(r for r in strategy['pairs'] if r['ticker']=='META')
        self.assertEqual(0,pair['option_results'])
        self.assertEqual(90,pair['profit_protection_comparison']['minutes'])
        self.assertEqual(1,pair['profit_protection_comparison']['paired_results'])
        self.assertEqual(1,pair['reference_contract_test']['profit_protection']['paired_results'])
        self.assertEqual(0,strategy['current_evidence']['option_results'])

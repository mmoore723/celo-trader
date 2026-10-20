import unittest
from unittest.mock import patch, Mock

from strategy_health import compression_exit as module
from tests import test_authored_exit_capture as fixtures
from tests.test_compression_exit_measurement import seed


class CompressionExitCaptureTests(unittest.TestCase):
    def test_research_and_order_dispatch_recover_same_missing_candle(self):
        from trading.research_order_exit import evaluate_exit
        from tests.test_research_order_execution import position
        self.seed()
        complete=self.f.frame.copy()
        self.f.frame=self.f.frame.drop(index=1)
        repair=Mock(return_value=complete)
        self.f.capture(compression_bars_lookup=repair)
        result=self.f.rows()[0]
        self.assertEqual((result['status'],result['reason']),('priced','underlying_stop'))
        repair.assert_called_once_with('META')
        trade=position(module.STRATEGY_ID,authored_exit_protocol=module.PROTOCOL,
                       authored_exit_state=seed(),underlying_stop=98,underlying_target=104)
        self.assertEqual(evaluate_exit(trade,'2026-09-10T10:05:03',self.f.now,self.f.frame,
                                      compression_bars_lookup=lambda:complete),
                         (True,'research_underlying_stop'))

    def setUp(self):
        self.f=fixtures.AuthoredExitCaptureTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def seed(self,name='compression',**changes):
        args=dict(strategy_id=module.STRATEGY_ID,protocol=module.PROTOCOL,state=seed())
        self.f.seed(name,**{**args,**changes})

    def test_forty_overlapping_plays_no_allocation_cooldown_and_restart(self):
        for i in range(40):
            self.seed(str(i))
        self.f.capture()
        self.assertEqual(40,len(self.f.rows()))
        self.assertTrue(all(r['status']=='priced' and r['reason']=='underlying_stop' for r in self.f.rows()))
        self.assertTrue(all(r['decision_at']=='2026-09-10T10:11:00' for r in self.f.rows()))
        self.f.quote.assert_called_once_with('XYZ')
        self.f.capture()
        self.f.quote.assert_called_once_with('XYZ')

    def test_account_and_protocol_isolation(self):
        self.seed(); self.seed('other',account='b')
        self.seed('wrong',strategy_id='V2_ORB_PULLBACK')
        self.f.capture()
        self.assertEqual(['compression'],[r['candidate_id'] for r in self.f.rows()])

    def test_missing_state_and_late_entry_ask_cannot_be_priced(self):
        self.seed(state=None); self.seed('late')
        with self.f.connect() as conn:
            conn.execute("UPDATE candidate_option_quote_observations SET observed_at='2026-09-10T10:06' WHERE candidate_id='late'")
        self.f.capture()
        self.assertEqual(['missing_exit_state','late_entry_quote'],[r['reason'] for r in self.f.rows()])
        self.assertTrue(all(r['status']=='unmeasurable' for r in self.f.rows()))
        self.f.quote.assert_not_called()

    def test_missing_option_quote_never_backfills_from_later_prices(self):
        self.seed()
        self.f.quote.return_value={}
        self.f.capture()
        from datetime import datetime
        self.f.now=datetime(2026,9,10,10,17)
        self.f.capture()
        self.assertEqual('missing_quote',self.f.rows()[0]['status'])
        self.assertIsNone(self.f.rows()[0]['bid'])

    def test_matrix_keeps_30_minute_results_separate(self):
        from strategy_health.research_matrix import build_research_matrix
        self.seed(); self.f.capture()
        with patch('database.get_conn',self.f.connect),patch('database._now_et',return_value=self.f.now),patch(
            'config.get_settings',return_value={'active_broker_account_id':'a','research_strategy_ids':[module.STRATEGY_ID]},
        ),patch('scanner.state_io._read_daily_universe',return_value={}):
            matrix=build_research_matrix()
        strategy=next(s for s in matrix['strategies'] if s['strategy_id']==module.STRATEGY_ID)
        pair=next(p for p in strategy['pairs'] if p['ticker']=='META')
        self.assertTrue(strategy['exit_measurement']['authored_collector_enabled'])
        self.assertEqual('Strategy-exit PF',strategy['exit_measurement']['pf_label'])
        self.assertEqual(1,pair['option_results'])
        self.assertTrue(all(r['option_results'] == 0 for r in pair['exit_comparison']))
        evidence=pair['authored_exit_evidence']
        self.assertEqual(1,evidence['option_results'])
        self.assertEqual(module.PROTOCOL,evidence['protocol'])
        self.assertEqual(-83.3,evidence['net_one_contract_pnl'])

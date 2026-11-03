from datetime import datetime, timedelta
import json
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from config.research_pair_policy import build, selected, validate
from config.admin_strategy_overrides import updates
from trading.research_order_exit import evaluate_exit
from trading.entry.exit_deadline import freeze_at_fill
from trading.research_contract_selection import select_research_contract
from tests.test_research_contract_selection import _Tradier
from tests.test_research_order_execution import position

SID = 'V2_AFTERNOON_REVERSAL'
VERSION = 'research.1'


class SelectedPairPolicyTests(unittest.TestCase):
    def test_selection_is_exact_pair_version_and_shared_across_modes(self):
        base = {'paper_trading': True, 'risk_per_trade': .1}
        changes = updates(base, SID, 'QQQ', VERSION, True, 'admin', exit_minutes=90, contract_policy='closest_otm_150_1000')
        self.assertNotIn('paper_trading', changes)
        self.assertNotIn('risk_per_trade', changes)
        for mode in (True, False):
            settings = {**base, **changes, 'paper_trading': mode}
            self.assertEqual(90, selected(settings, SID, 'QQQ', VERSION)['exit_minutes'])
            self.assertIsNone(selected(settings, SID, 'SPY', VERSION))
            self.assertIsNone(selected(settings, SID, 'QQQ', 'wrong'))

    def test_unknown_settings_and_tampering_fail_closed(self):
        for minutes, contract in [(1,None), (True,None), (None,'invented')]:
            with self.assertRaises(ValueError): build(SID,'QQQ',VERSION,minutes,contract)
        p = build(SID,'QQQ',VERSION,90,'closest_otm_150_1000')
        for changed in ({**p,'ticker':'SPY'}, {**p,'exit_minutes':30}, 'invalid'):
            with self.assertRaises(ValueError): validate(changed,SID,'QQQ',VERSION)

    def test_selected_timer_replaces_native_exit_and_needs_no_quotes_or_bars(self):
        start = datetime(2026,11,3,13,tzinfo=ZoneInfo('America/New_York'))
        p = build(SID,'QQQ',VERSION,90,'closest_otm_150_1000')
        trade = {**position(SID, selected_test_policy=p), 'ticker':'QQQ'}
        with patch('trading.research_order_exit.first_exit', side_effect=AssertionError('Native exit must not override selected timer')):
            self.assertEqual((False,'hold'),evaluate_exit(trade,start,start+timedelta(minutes=89),None))
            self.assertEqual((True,'selected_test_90m'),evaluate_exit(trade,start,start+timedelta(minutes=90),None))
        # Later settings changes do not affect the frozen trade policy.
        with patch('config.get_settings', return_value={'admin_strategy_overrides':{}}):
            self.assertTrue(evaluate_exit(trade,start,start+timedelta(minutes=90),None)[0])

    def test_mandatory_session_exit_still_wins(self):
        start = datetime(2026,11,3,15,tzinfo=ZoneInfo('America/New_York'))
        trade = {**position(SID, selected_test_policy=build(SID,'QQQ',VERSION,120)), 'ticker':'QQQ'}
        self.assertEqual((True,'research_session_close'),evaluate_exit(trade,start,start.replace(minute=55),None))
        self.assertEqual((True,'research_session_close'),evaluate_exit(trade,start,start.replace(hour=12,minute=55),None,
                         session_close=start.replace(hour=13,minute=0)))

    def test_unselected_positions_keep_native_exit(self):
        start = datetime(2026,11,3,13,tzinfo=ZoneInfo('America/New_York'))
        trade = position(SID)
        self.assertEqual((False,'waiting_for_bars'),evaluate_exit(trade,start,start+timedelta(minutes=90),None))

    def test_selected_deadline_is_frozen_at_fill(self):
        context = {'selected_test_policy':build(SID,'QQQ',VERSION,90), 'exit_deadline_capture': {
            'status':'awaiting_fill','strategy_id':SID,'strategy_version':VERSION,
            'session_cap':'2026-11-03T15:55:00-05:00','hold_minutes':None}}
        result=freeze_at_fill(context,'2026-11-03T13:00:00-05:00')
        self.assertEqual('2026-11-03T14:30:00-05:00',result['exit_deadline'])
        self.assertEqual(90,result['exit_deadline_capture']['hold_minutes'])

    def test_contract_selection_uses_choice_without_fallback(self):
        reader = _Tradier(['2026-09-04'], {'2026-09-04':[
            {'symbol':'NEAR','strike':101,'bid':3.9,'ask':4.0,'volume':1},
            {'symbol':'CHEAP','strike':102,'bid':2.9,'ask':3.0,'volume':100}]})
        with patch('trading.research_contract_selection._now_et',return_value=datetime(2026,9,1,10)):
            for policy, symbol in [('closest_otm_150_1000','NEAR'),('lowest_ask_150_1000','CHEAP'),('highest_volume_150_1000','CHEAP')]:
                result,info=select_research_contract(reader,'QQQ','bullish',100,SID,policy_override=policy)
                self.assertEqual(symbol,result['symbol']);self.assertEqual(policy,info['selected_policy'])
            result,info=select_research_contract(reader,'QQQ','bullish',100,SID,policy_override='target_150_250')
            self.assertIsNone(result);self.assertEqual('selected_contract_policy_unavailable',info['reason'])

from datetime import timedelta
import json
import unittest
from unittest.mock import Mock

from strategy_health.option_profit_protection import initialize, advance, RECOVERY_PROTOCOL, RECOVERY_STRATEGY_ID, summary
from strategy_health.recovery_profit_protection import freeze, observe_target, can_arm
from database.option_profit_protection import capture
from tests.test_option_profit_protection import ENTRY, quote
from tests import test_option_profit_protection as fixtures


def state(direction='bullish'):
    return freeze(initialize(ENTRY,2,1.96),dict(v2_target=101 if direction=='bullish' else 99,v2_entry_reference=100),direction)


def bars():
    return [dict(time=(ENTRY+timedelta(minutes=i)).isoformat(),open=100,high=102,low=98,close=100) for i in range(31)]


class TargetTests(unittest.TestCase):
    def test_partial_entry_bar_wicks_and_future_closes_cannot_arm(self):
        frame=bars(); frame[0]['close']=102; frame[2]['close']=101
        s=observe_target(state(),frame,entry_at=ENTRY,now=ENTRY+timedelta(seconds=179))
        self.assertIsNone(s['target_detected_at'])
        s=observe_target(s,frame,entry_at=ENTRY,now=ENTRY+timedelta(seconds=180))
        self.assertEqual('2026-09-10T10:03:00',s['target_close_at'])

    def test_short_recovery_mirrors_target_not_option_trail(self):
        frame=bars();frame[1]['close']=99
        s=observe_target(state('bearish'),frame,entry_at=ENTRY,now=ENTRY+timedelta(seconds=120))
        self.assertEqual('2026-09-10T10:02:00',s['target_close_at'])
        self.assertTrue(can_arm(s,quote(2.2,121),ENTRY+timedelta(seconds=121)))

    def test_target_is_latched_and_never_uses_pre_target_high_bid(self):
        s=advance(state(),entry_at=ENTRY,ask=2,contract='XYZ',now=ENTRY+timedelta(seconds=30),quote=quote(3,30),allow_arm=False)
        self.assertIsNone(s['high_bid']);self.assertIsNone(s['stop'])
        frame=bars();frame[1]['close']=101
        s=observe_target(s,frame,entry_at=ENTRY,now=ENTRY+timedelta(seconds=120))
        self.assertFalse(can_arm(s,quote(2.2,120),ENTRY+timedelta(seconds=120)))
        self.assertTrue(can_arm(s,quote(2.2,600),ENTRY+timedelta(seconds=600)))
        frame[1]['close']=100
        self.assertEqual(s,observe_target(s,frame,entry_at=ENTRY,now=ENTRY+timedelta(seconds=180)))

    def test_missing_or_late_target_is_not_reconstructed_as_success(self):
        frame=bars();del frame[1]
        s=observe_target(state(),frame,entry_at=ENTRY,now=ENTRY+timedelta(seconds=241))
        self.assertEqual('missing_path',s['trail']['status'])
        self.assertEqual('collecting',s['control']['status'])
        frame=bars();frame[1]['close']=101
        s=observe_target(state(),frame,entry_at=ENTRY,now=ENTRY+timedelta(seconds=241))
        self.assertEqual('late_recovery_candle',s['trail']['reason'])

    def test_invalid_duplicate_and_wrong_direction_context(self):
        s=freeze(initialize(ENTRY,2,1.96),{'v2_target':99,'v2_entry_reference':100},'bullish')
        self.assertEqual('invalid_context',s['trail']['status'])
        frame=bars();frame.append(frame[1])
        s=observe_target(state(),frame,entry_at=ENTRY,now=ENTRY+timedelta(seconds=180))
        self.assertEqual('invalid_recovery_candle',s['trail']['reason'])


class RecoveryCaptureTests(unittest.TestCase):
    setUp = fixtures.CaptureTests.setUp
    connect = fixtures.CaptureTests.connect
    seed = fixtures.CaptureTests.seed
    rows = fixtures.CaptureTests.rows
    def recovery(self,name='recovery',account='a'):
        self.seed(name,account=account,protocol=RECOVERY_PROTOCOL)
        with self.connect() as conn:
            conn.execute('''UPDATE shadow_candidates SET strategy_id=?,direction='bullish',metadata_json=? WHERE candidate_id=?''',
                (RECOVERY_STRATEGY_ID,json.dumps(dict(strategy_version='2.1.0',profit_protection_protocol=RECOVERY_PROTOCOL,
                v2_target=101,v2_entry_reference=100)),name))

    def test_target_then_option_trail_and_shared_prices_across_strategies(self):
        self.seed('trend');self.recovery(); self.recovery('other',account='b')
        frame=bars();frame[1]['close']=101; lookup=Mock(return_value=frame)
        def step(seconds,bid):
            self.now=ENTRY+timedelta(seconds=seconds);self.lookup.return_value=quote(bid,seconds)
            capture(account='a',quote_lookup=self.lookup,bars_lookup=lookup,clock=lambda:self.now)
        step(30,2.2)
        self.assertIsNone(self.rows()['recovery']['state']['stop'])
        self.assertIsNotNone(self.rows()['trend']['state']['stop'])
        step(90,2.2);step(120,2.2)
        self.assertIsNone(self.rows()['recovery']['state']['stop'])
        step(150,2.2)
        self.assertAlmostEqual(2.12,self.rows()['recovery']['state']['stop'])
        n=lookup.call_count
        step(180,2.1);step(210,2.08)
        self.assertEqual(n,lookup.call_count)
        self.assertEqual('priced',self.rows()['recovery']['state']['trail']['status'])
        step(1801,1.95)
        result=summary([{'candidate_id':'recovery'},{'candidate_id':'trend'}],self.rows(),RECOVERY_STRATEGY_ID)
        self.assertEqual(1,result['paired_results']);self.assertEqual(1,result['target_reached'])
        self.assertEqual(RECOVERY_PROTOCOL,result['protocol']);self.assertEqual(7,self.lookup.call_count)

    def test_all_recovery_overlaps_share_one_candle_lookup(self):
        for i in range(40):self.recovery(str(i))
        lookup=Mock(return_value=bars())
        capture(account='a',quote_lookup=self.lookup,bars_lookup=lookup,clock=lambda:self.now)
        lookup.assert_called_once_with('META');self.lookup.assert_called_once_with('XYZ')
        self.assertEqual(40,len(self.rows()))

    def test_bar_failure_does_not_block_priced_control(self):
        self.recovery();self.now=ENTRY+timedelta(seconds=1801);self.lookup.return_value=quote(1.95,1801)
        capture(account='a',quote_lookup=self.lookup,bars_lookup=Mock(side_effect=RuntimeError('offline')),clock=lambda:self.now)
        s=self.rows()['recovery']['state']
        self.assertEqual('priced',s['control']['status']);self.assertEqual('missing_path',s['trail']['status'])

    def test_never_reached_target_preserves_exact_control(self):
        self.recovery()
        for seconds in range(30,1800,30):
            self.now=ENTRY+timedelta(seconds=seconds);self.lookup.return_value=quote(2.2,seconds)
            capture(account='a',quote_lookup=self.lookup,bars_lookup=lambda _:bars(),clock=lambda:self.now)
        self.now=ENTRY+timedelta(seconds=1801);self.lookup.return_value=quote(1.95,1801)
        capture(account='a',quote_lookup=self.lookup,bars_lookup=lambda _:bars(),clock=lambda:self.now)
        s=self.rows()['recovery']['state']
        self.assertEqual(s['control'],s['trail']);self.assertIsNone(s['stop'])

import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock

from research.jobs.replay_spy_structure_exit import evaluate_pair
from research.jobs.structure_exit_candidate import ET


class SpyStructureReplayTests(unittest.TestCase):
    def setUp(self):
        self.start=datetime(2026,6,1,12,0,tzinfo=ET)
        self.entry=dict(date='2026-06-01',candidate_id='example',independent=True,
            contract='SPY_OPTION',entry_time=self.start.isoformat(),direction='bullish',
            stock_reference=100,signal_meta={'v2_stop':99},entry_ask=5,entry_bid=5,
            exit_time=(self.start+timedelta(minutes=31)).isoformat(),exit_bid=5.5,
            net_pnl_one_contract=46.7)
        self.path=[dict(contract='SPY_OPTION',time=(self.start+timedelta(minutes=i)).isoformat(),
            bid='5.5' if i==31 else '5',ask='5.5',bid_size='1',ask_size='1') for i in range(32)]
        self.path[0]['ask']='5'
        good=dict(close=101,fast=101,slow=100,histogram=1,histogram_change=1,rsi=60)
        self.market=Mock()
        self.market.at.side_effect=lambda t:dict(time=t,close=100,open=100,relative_volume=1,
            supports=[],resistances=[],frames={n:good for n in (1,5,15,60)})

    def run_pair(self):
        return evaluate_pair(self.entry,dict(snapshots=self.path),self.market)

    def test_control_exactly_reproduced_with_30_minute_decision(self):
        result=self.run_pair()
        self.assertEqual('46.70',result['control']['net'])
        self.assertEqual(result['control']['net'],result['variant']['net'])
        self.assertEqual((self.start+timedelta(minutes=30)).isoformat(),result['variant']['decision_at'])

    def test_guard_fills_at_later_bid_not_trigger_bid(self):
        self.path[1]['bid']='4'
        self.path[2]['bid']='3.9'
        result=self.run_pair()
        self.assertEqual('3.9',result['variant']['bid'])
        self.assertEqual('maximum_premium_loss_20pct',result['variant']['reason'])

    def test_missing_later_quote_cannot_be_fabricated(self):
        self.path[1]['bid']='4'
        del self.path[2]
        self.assertEqual('missing_quote',self.run_pair()['variant']['status'])

    def test_bad_control_prevents_comparison(self):
        self.entry['exit_bid']=6
        with self.assertRaisesRegex(ValueError,'control'):
            self.run_pair()

    def test_duplicate_conflicting_quote_rejected(self):
        self.path.append({**self.path[1],'bid':'4.9'})
        with self.assertRaisesRegex(ValueError,'Conflicting'):
            self.run_pair()

    def test_missing_candles_are_not_counted_as_a_hold(self):
        self.market.at.side_effect=ValueError('Missing completed candle')
        result=self.run_pair()
        self.assertEqual('missing_context',result['variant']['status'])
        self.assertEqual('priced',result['control']['status'])


if __name__=='__main__':
    unittest.main()

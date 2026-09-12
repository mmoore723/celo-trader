from datetime import datetime,timedelta
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import pandas as pd
import zstandard

from research.jobs.replay_spy_affordable_contracts import choose,day_replay,snapshots,COLUMNS


class AffordableProfileTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime.fromisoformat('2026-05-12T16:51:00+00:00')
        self.entry=dict(id='test',strategy_id='V2_SPY_TREND_CONT',independent=True,
            date='2026-05-12',direction='bullish',stock_reference=760,
            contract='SPY   260519C00761000',entry_time=self.now.isoformat(),entry_ask=5,entry_bid=4.99,
            exit_time=(self.now+timedelta(minutes=31)).isoformat(),exit_bid=5.2,net_pnl_one_contract=16.7)

    def raw(self,symbol='SPY   260519C00775000',bid='1.18',ask='1.20',now=None):
        return dict(ts_recv=(now or self.now).isoformat(),rtype='193',symbol=symbol,
                    bid_px_00=bid,ask_px_00=ask,bid_sz_00='1',ask_sz_00='1')

    def test_keeps_nearest_strike_ranking_under_budget(self):
        rows=[self.raw(self.entry['contract'],'4.99','5'),self.raw(),
              self.raw('SPY   260519C00780000','1','1.02')]
        self.assertEqual('SPY   260519C00775000',choose(self.entry,rows,self.now)['contract'])

    def test_budget_spread_direction_and_size_filters(self):
        for row in [self.raw(ask='1.43'),self.raw(bid='.9'),
                    self.raw('SPY   260519P00750000'),self.raw('SPY   260519C00759000'),
                    {**self.raw(),'bid_sz_00':'0'},self.raw(ask='NaN')]:
            with self.subTest(row=row):
                self.assertIsNone(choose(self.entry,[row],self.now))

    def test_does_not_use_fourth_expiry(self):
        rows=[self.raw(f'SPY   2605{day}C00775000','5','5.1') for day in ('19','20','21')]
        rows.append(self.raw('SPY   260522C00775000'))
        self.assertIsNone(choose(self.entry,rows,self.now))

    def groups(self,affordable=True):
        start=[self.raw(self.entry['contract'],'4.99','5')]
        if affordable:start.append(self.raw())
        end=self.now+timedelta(minutes=31)
        return [(self.now,pd.DataFrame(start)),(end,pd.DataFrame([
            self.raw(self.entry['contract'],'5.2','5.21',end),
            self.raw(bid='1.3',ask='1.32',now=end)]))]

    def test_control_and_candidate_use_same_entry_exit_clocks(self):
        with patch('research.jobs.replay_spy_affordable_contracts.snapshots',return_value=self.groups()):
            row=day_replay([self.entry],None)[0]
        self.assertEqual('16.70',row['control']['net'])
        self.assertEqual('6.70',row['candidate']['net'])
        self.assertEqual(row['control']['entry_time'],row['candidate']['entry_time'])
        self.assertEqual(row['control']['exit_time'],row['candidate']['exit_time'])
        self.assertFalse(row['control_fits_initial_budget'])

    def test_missing_affordable_contract_is_not_hidden(self):
        with patch('research.jobs.replay_spy_affordable_contracts.snapshots',return_value=self.groups(False)):
            row=day_replay([self.entry],None)[0]
        self.assertEqual('priced',row['control']['status'])
        self.assertEqual('no_affordable_contract',row['candidate']['status'])

    def test_changed_control_prevents_comparison(self):
        self.entry['net_pnl_one_contract']=100
        with patch('research.jobs.replay_spy_affordable_contracts.snapshots',return_value=self.groups()):
            with self.assertRaisesRegex(ValueError,'exit/costs'):
                day_replay([self.entry],None)

    def snapshot_fixture(self,rows):
        td=tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        path=Path(td.name)/'fixture.zst'
        path.write_bytes(zstandard.ZstdCompressor().compress(pd.DataFrame(rows)[COLUMNS].to_csv(index=False).encode()))
        return path

    def test_split_timestamp_groups_are_not_selected_early(self):
        path=self.snapshot_fixture([self.raw(),self.raw('SPY   260519C00780000'),
                                   self.raw(now=self.now+timedelta(minutes=1))])
        original=pd.read_csv
        def tiny(source,**kwargs):
            return original(source,**{**kwargs,'chunksize':1})
        with patch('research.jobs.replay_spy_affordable_contracts.pd.read_csv',side_effect=tiny):
            groups=list(snapshots(path))
        self.assertEqual([2,1],[len(group) for _,group in groups])

    def test_out_of_order_archive_rejected(self):
        path=self.snapshot_fixture([self.raw(now=self.now+timedelta(minutes=1)),self.raw()])
        with self.assertRaisesRegex(ValueError,'not ordered'):
            list(snapshots(path))


if __name__=='__main__':unittest.main()

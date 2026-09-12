from datetime import datetime
import io
import unittest
from unittest.mock import patch
import pandas as pd
import zstandard

from research.jobs.replay_displacement_affordable import choose, price_day, csv_groups, COLUMNS


def raw(strike, ask, bid=None, symbol=None):
    return dict(symbol=symbol or f'TSLA  260605C{strike*1000:08d}', rtype='193',
                bid_px_00=str(bid if bid is not None else ask-.01), ask_px_00=str(ask),
                bid_sz_00='5', ask_sz_00='5')


class AffordableDisplacementTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.fromisoformat('2026-06-01T12:31:00-04:00')
        self.entry = dict(candidate_id='one', ticker='TSLA', stock_reference=100,
                          entry_snapshot_at=self.now.isoformat(), contract='TSLA  260605C00105000',
                          entry_ask='2', entry_bid='1.99', legs={
                            'structural': dict(quote_at='2026-06-01T12:33:00-04:00', exit_bid='2.2', net_pnl_one_contract=16.7),
                            'timer': dict(quote_at='2026-06-01T12:35:00-04:00', exit_bid='2.1', net_pnl_one_contract=6.7)})

    def groups(self):
        return [(self.now, pd.DataFrame([raw(105,2,1.99),raw(110,1.4,1.39)])),
                (datetime.fromisoformat(self.entry['legs']['structural']['quote_at']),
                 pd.DataFrame([raw(105,2.21,2.2),raw(110,1.7,1.69)])),
                (datetime.fromisoformat(self.entry['legs']['timer']['quote_at']),
                 pd.DataFrame([raw(105,2.11,2.1),raw(110,1.5,1.49)]))]

    def test_candidate_changes_premium_band_not_expiry_or_ranking(self):
        rows=[raw(105,2),raw(110,1.4),raw(108,1.42),raw(107,1.43),raw(102,.79),
              raw(99,1.42),raw(106,1.42,symbol='TSLA  260619C00106000')]
        selected=choose(self.entry, rows, self.now)
        self.assertEqual('TSLA  260605C00105000', selected['control']['contract'])
        self.assertEqual('TSLA  260605C00108000', selected['candidate']['contract'])

    def test_wide_spread_is_not_made_affordable(self):
        self.assertIsNone(choose(self.entry,[raw(110,1.42,1)],self.now)['candidate'])

    def test_control_prices_and_two_exit_clocks_reproduce(self):
        result=price_day([self.entry],self.groups())[0]
        self.assertEqual('16.70',result['legs']['control']['structural']['net'])
        self.assertEqual('25.70',result['legs']['candidate']['structural']['net'])
        self.assertEqual('5.70',result['legs']['candidate']['timer']['net'])

    def test_missing_candidate_exit_stays_missing(self):
        groups=self.groups()
        groups[-1]=(groups[-1][0],groups[-1][1].iloc[:1])
        result=price_day([self.entry],groups)[0]
        self.assertEqual('missing_exit',result['legs']['candidate']['timer']['status'])

    def test_original_contract_must_be_reproduced(self):
        self.entry['entry_ask']='2.01'
        with self.assertRaisesRegex(ValueError,'entry price'):
            price_day([self.entry],self.groups())

    def test_conflicting_snapshots_rejected(self):
        with self.assertRaisesRegex(ValueError,'Conflicting entry'):
            choose(self.entry,[raw(105,2),raw(105,2.01)],self.now)

    def test_missing_entry_snapshot_is_not_no_contract(self):
        with self.assertRaisesRegex(ValueError,'Missing original'):
            price_day([self.entry],self.groups()[1:])

    def test_csv_chunk_boundary_keeps_whole_entry_book(self):
        rows=[dict(raw(105,2),ts_recv=self.now.isoformat()),dict(raw(110,1.4),ts_recv=self.now.isoformat())]
        stream=io.BytesIO(zstandard.ZstdCompressor().compress(pd.DataFrame(rows)[COLUMNS].to_csv(index=False).encode()))
        original=pd.read_csv
        with patch('research.jobs.replay_displacement_affordable.pd.read_csv',
                   side_effect=lambda source,**kwargs:original(source,**{**kwargs,'chunksize':1})):
            groups=list(csv_groups(stream))
        self.assertEqual([2],[len(group) for _,group in groups])

    def test_wrong_schema_cannot_be_used_as_minute_quotes(self):
        row=dict(raw(105,2),ts_recv=self.now.isoformat(),rtype='1')
        stream=io.BytesIO(zstandard.ZstdCompressor().compress(pd.DataFrame([row])[COLUMNS].to_csv(index=False).encode()))
        with self.assertRaisesRegex(ValueError,'Wrong CSV schema'):
            list(csv_groups(stream))


if __name__=='__main__':
    unittest.main()

from datetime import datetime, timedelta
import unittest
from unittest.mock import Mock, patch

import pandas as pd
from trading.research_ema_history import with_native_ema_history, native_ema_history
from trading.tested_strategy_research import evaluate_tested_research
from tests.test_ema_exit_measurement import setup_bars, seed
from strategy_health.ema_exit import first_exit


def native_frame(bars):
    return pd.DataFrame([dict(time=b.timestamp, open=b.open, high=b.high,
                             low=b.low, close=b.close, volume=b.volume) for b in bars])


class NativeEmaTests(unittest.TestCase):
    def setUp(self):
        self.bars=setup_bars(1,0)[:372]
        self.now=datetime(2026,9,10,11,30)

    def test_sparse_minutes_can_emit_genuine_source_signal_without_fake_candles(self):
        with patch('trading.tested_strategy_research._emitted',set()):
            signals=evaluate_tested_research(pd.DataFrame(),'NVS',['V2_EMA_PULLBACK_RTH'],
                scope='native',now=self.now,history_15m=native_frame(self.bars))
        self.assertEqual(1,len(signals))
        self.assertEqual('research.3',signals[0].meta['strategy_version'])
        self.assertTrue(signals[0].meta['observation_only'])
        self.assertEqual(pd.Timestamp(self.now),signals[0].trigger_bar)
        self.assertEqual(365,signals[0].meta['authored_exit_state']['config']['trend_ema'])

    def test_stale_incomplete_duplicate_and_invalid_last_candle_cannot_signal(self):
        f=native_frame(self.bars)
        for bad in (f.iloc[:-1],pd.concat([f,f.iloc[[-1]]]),f.assign(high=float('nan'))):
            self.assertEqual((),with_native_ema_history((),bad,self.now))
        partial=with_native_ema_history((),f,self.now-timedelta(seconds=1))
        self.assertTrue(all(b.timestamp<self.bars[-1].timestamp for b in partial))

    def test_collected_wins_and_future_native_candles_do_not_advance(self):
        f=native_frame(setup_bars(1,0))
        f.loc[f.time==self.bars[-1].timestamp,'close']=f.loc[f.time==self.bars[-1].timestamp,'open']
        got=with_native_ema_history(tuple(self.bars[-2:]),f,self.now)
        self.assertEqual(self.bars[-2:],list(got[-2:]))
        self.assertEqual(self.bars[-1].timestamp,got[-1].timestamp)

    def test_cache_is_account_scoped_bounded_and_refreshes_each_completed_bar(self):
        market=Mock(); state={}
        f=native_frame(self.bars)
        market.get_bars.return_value=([dict(t=pd.Timestamp(r.time).tz_localize('America/New_York').isoformat(),
            o=r.open,h=r.high,l=r.low,c=r.close,v=r.volume) for r in f.itertuples()],False)
        native_ema_history(market,'NVS',state,self.now,'a')
        native_ema_history(market,'NVS',state,self.now+timedelta(seconds=10),'a')
        self.assertEqual(1,market.get_bars.call_count)
        native_ema_history(market,'NVS',state,self.now,'b')
        native_ema_history(market,'NVS',state,self.now+timedelta(minutes=15),'a')
        self.assertEqual(3,market.get_bars.call_count)

    def test_cache_bound_and_archival_keeps_only_real_completed_today_bars(self):
        market=Mock(); archive=Mock()
        f=native_frame(setup_bars(1,0))
        market.get_bars.return_value=([dict(t=pd.Timestamp(r.time).tz_localize('America/New_York').isoformat(),
            o=r.open,h=r.high,l=r.low,c=r.close,v=r.volume) for r in f.itertuples()],False)
        state={'ema_native_history':{('old',str(i),'X'):{} for i in range(128)}}
        native_ema_history(market,'NVS',state,self.now,'a',archive=archive)
        self.assertEqual(128,len(state['ema_native_history']))
        stored=archive.call_args.args[0]
        self.assertTrue(all(t.date()==self.now.date() and t+timedelta(minutes=15)<=self.now for t in stored.time))
        self.assertLessEqual(len(stored),26)
        native_ema_history(market,'NVS',state,self.now,'a',archive=archive)
        archive.assert_called_once()

    def test_native_exit_skips_entry_bar_and_waits_for_completed_bar(self):
        f=pd.DataFrame([dict(time=datetime(2026,9,10,10,i),open=100,high=105,low=97,close=100,volume=1)
                        for i in (0,15)])
        f.attrs['source_minutes']=15
        args=dict(entry_at='2026-09-10T10:00',entry_quote_at='2026-09-10T10:00:03',
                  stop=98,target=104,direction='bullish',seed=seed())
        self.assertIsNone(first_exit(f,**args,now='2026-09-10T10:29:59'))
        self.assertEqual((datetime(2026,9,10,10,30),'underlying_stop'),
                         first_exit(f,**args,now='2026-09-10T10:30'))
        self.assertEqual('missing_bars',first_exit(f.iloc[:1],**args,now='2026-09-10T10:36')[1])


if __name__=='__main__':unittest.main()

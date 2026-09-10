from datetime import datetime, timedelta
import unittest
from unittest.mock import patch

import pandas as pd
from trading.research_ema_history import with_ema_history
from trading.tested_strategy_research import evaluate_tested_research
from tests.test_ema_exit_measurement import setup_bars, minute_frame


def five_minute_frame(bars):
    return pd.DataFrame([dict(time=b.timestamp+timedelta(minutes=i),open=b.open,high=b.high,
                             low=b.low,close=b.close,volume=b.volume/3) for b in bars for i in (0,5,10)])


class ResearchEmaHistoryTests(unittest.TestCase):
    def setUp(self):
        self.bars=setup_bars(1,0)[:372]
        self.now=datetime(2026,9,10,11,30)

    def test_true_five_minute_history_supplies_warmup_without_lowering_minimum(self):
        current=minute_frame(self.bars[-1:])
        def evaluate(history):
            with patch('trading.tested_strategy_research._emitted',set()):
                return evaluate_tested_research(current,'META',['V2_EMA_PULLBACK_RTH'],
                    scope='history-test',now=self.now,history_5m=history)
        self.assertEqual([],evaluate(None))
        results=evaluate(five_minute_frame(self.bars[:-1]))
        self.assertEqual(1,len(results))
        self.assertEqual('research.3',results[0].meta['strategy_version'])
        self.assertEqual('complete_15m_collected_preferred_fetched5m_gaps_v1',results[0].meta['history_policy'])
        self.assertEqual(365,results[0].meta['authored_exit_state']['config']['trend_ema'])
        self.assertEqual(pd.Timestamp(self.now),results[0].trigger_bar)

    def test_collected_bar_wins_and_future_history_cannot_advance_signal(self):
        history=five_minute_frame(setup_bars(1,0))
        history.loc[history.time>=self.bars[-1].timestamp,'close']=999
        merged=with_ema_history(tuple(self.bars[-2:]),history,self.now)
        self.assertEqual(self.bars[-2:],list(merged[-2:]))
        self.assertTrue(all(b.timestamp<=self.bars[-1].timestamp for b in merged))

    def test_incomplete_invalid_or_duplicate_history_never_forms_full_bar(self):
        history=five_minute_frame(self.bars[:1])
        for invalid in (history.drop(index=1),pd.concat([history,history.iloc[[1]]]),
                        history.assign(high=float('nan'))):
            self.assertEqual(tuple(self.bars[-1:]),with_ema_history(tuple(self.bars[-1:]),invalid,self.now))

    def test_empty_current_cannot_emit_from_history_and_bad_schema_falls_back(self):
        self.assertEqual((),with_ema_history((),five_minute_frame(self.bars),self.now))
        with self.assertLogs('celo_trader.research',level='WARNING'):
            result=with_ema_history(tuple(self.bars[-1:]),pd.DataFrame({'bad':[1]}),self.now)
        self.assertEqual(tuple(self.bars[-1:]),result)

    def test_timezone_conversion_and_regular_session_exclusion(self):
        history=five_minute_frame(self.bars[:1])
        history['time']=pd.to_datetime(history['time']).dt.tz_localize('America/New_York').dt.tz_convert('UTC')
        merged=with_ema_history(tuple(self.bars[-1:]),history,self.now)
        self.assertEqual(self.bars[0],merged[0])
        history['time']=history['time']-timedelta(hours=2)
        self.assertEqual(tuple(self.bars[-1:]),with_ema_history(tuple(self.bars[-1:]),history,self.now))

    def test_history_is_not_used_by_five_minute_strategies(self):
        with patch('trading.research_ema_history.with_ema_history') as merge:
            evaluate_tested_research(minute_frame(self.bars[-1:]),'META',['V2_TREND_CONT'],
                scope='other-strategy',now=self.now,history_5m=five_minute_frame(self.bars))
        merge.assert_not_called()

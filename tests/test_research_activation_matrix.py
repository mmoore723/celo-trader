"""Full research inventory, approval isolation and shared-engine parity."""
from copy import deepcopy
from datetime import datetime, timedelta
import unittest
from unittest.mock import patch
import pandas as pd
from config.research_order_specs import SPECS, EXTENDED, execution_id
from config.strategy_catalog import REVIEWED_STRATEGIES, enabled_reviewed_strategy_ids, reviewed_strategy_integrity_errors
from config.admin_strategy_overrides import updates, active
from config.research_activation import capability
from strategies import research_orders
from trading.tested_strategy_research import TESTED_RESEARCH_STRATEGIES, evaluate_tested_research, _research_bars, _latest_candidate
from tests.test_momentum_exit_measurement import frame
from research.engine.models import Bar

TICKERS = 'AAPL AMD AMZN BABA COIN GOOG GOOGL META MSFT MU NFLX NKE NVDA OKTA PANW PLTR QQQ SHOP SPY TSLA'.split()
INVENTORY = {source: spec.version for source, spec in TESTED_RESEARCH_STRATEGIES.items()}
INVENTORY.update({source: row[1] for source,row in EXTENDED.items()})
INVENTORY.update(CTX_ORB_PRIOR_RANGE_LT_ATR10_LONG='0.1.0.research.2', V2_FAILED_OR_BREAK_VWAP_REVERSION='2.1.0.research.2')

class ActivationMatrixTests(unittest.TestCase):
    def test_all_520_pairs_are_connected_but_none_new_are_authorized(self):
        self.assertEqual(26,len(INVENTORY)); self.assertEqual({},reviewed_strategy_integrity_errors())
        settings={'paper_trading':True,'active_broker_account_id':'a','risk_pct':1.5}
        before=deepcopy(settings)
        for source,version in INVENTORY.items():
            for ticker in TICKERS:
                with self.subTest(source=source,ticker=ticker):
                    result=capability(settings,source,ticker,version)
                    self.assertTrue(result['ready'], result)
                    self.assertFalse(result['approved'])
                    sid=result['strategy_id']
                    self.assertNotIn(sid,enabled_reviewed_strategy_ids(settings,ticker=ticker))
        self.assertEqual(before,settings)

    def test_each_pair_approval_persists_exact_selection_without_global_changes(self):
        for source,version in INVENTORY.items():
            for ticker in TICKERS:
                sid=execution_id(source,version,ticker)
                settings={'paper_trading':True,'risk_pct':1.5,'active_broker_account_id':'a'}
                configurable=sid in SPECS
                changes=updates(settings,source,ticker,version,True,'admin',
                                exit_minutes=60 if configurable else None,
                                contract_policy='tightest_spread_150_1000' if configurable else None)
                self.assertNotIn('paper_trading',changes);self.assertNotIn('risk_pct',changes)
                saved={**settings,**changes}
                grant=saved['admin_strategy_overrides'][f'{sid}:{ticker}']
                self.assertEqual(version,grant['strategy_version'])
                if configurable:
                    from config.research_pair_policy import selected
                    self.assertEqual(60,selected(saved,sid,ticker,version)['exit_minutes'])
                for paper in (True,False):
                    current={**saved,'paper_trading':paper}
                    self.assertIn(sid,enabled_reviewed_strategy_ids(current,ticker=ticker))
                    self.assertNotIn(sid,enabled_reviewed_strategy_ids(current,ticker='UNAPPROVED'))
                self.assertFalse(active(settings,sid,ticker))

    def test_existing_routes_unchanged(self):
        for source,version,ticker,expected in [
            ('V2_SPY_TREND_CONT','2.1.0','SPY','V2_SPY_TREND_CONT'),
            ('V2_SPY_TREND_CONT','2.1.0','QQQ','RESEARCH_QQQ_TREND_V2'),
            ('V2_TREND_CONT','research.1','QQQ','V2_TREND_CONT'),
            ('V2_VWAP_PULLBACK','research.1','AMZN','V2_VWAP_PULLBACK'),
            ('V2_SPY_AFTERNOON_FVG','2.1.0','SPY','V2_SPY_AFTERNOON_FVG')]:
            self.assertEqual(expected,execution_id(source,version,ticker))

    def test_momentum_mu_real_signal_matches_research_both_directions(self):
        for sign in (1,-1):
            before=datetime(2026,9,9,14,45);day=datetime(2026,9,10,9,30)
            bars=[Bar(before+timedelta(minutes=5*i),100,101,99,100,100) for i in range(15)]
            for i in range(6):
                c=100+sign*(i+1)*.2
                bars.append(Bar(day+timedelta(minutes=5*i),100,max(100,c)+.1,min(100,c)-.1,c,100))
            tape=frame(bars);now=day+timedelta(minutes=30)
            source='V2_OPENING_MOMENTUM_RTH_EXPLORATORY';sid=execution_id(source,'research.1','MU')
            with patch('database.load_scanner_candles',return_value=pd.DataFrame()),patch('trading.tested_strategy_research._emitted',set()),patch.object(research_orders,'_emitted',{}):
                expected=evaluate_tested_research(tape,'MU',[source],scope='test',now=now)
                actual=research_orders.evaluate(tape,'MU',execution_scope='orders',now=now,strategy_id=sid)
                self.assertEqual(1,len(expected));self.assertIsNotNone(actual)
                for key in ('underlying_stop','underlying_target','authored_exit_protocol','authored_exit_state'):
                    self.assertEqual(expected[0].meta[key],actual.meta[key])
                self.assertEqual(expected[0].direction,actual.direction)
                self.assertIsNone(research_orders.evaluate(tape,'MU',execution_scope='orders',now=now,strategy_id=sid))

    def test_unknown_version_and_integrity_never_grant_permission(self):
        self.assertFalse(capability({},'V2_VWAP_PULLBACK','MU','wrong')['ready'])
        sid=execution_id('V2_VWAP_PULLBACK','research.1','MU')
        with patch('config.strategy_catalog.reviewed_strategy_integrity_errors',return_value={sid:('tampered',)}):
            self.assertFalse(capability({},'V2_VWAP_PULLBACK','MU','research.1')['ready'])
            with self.assertRaises(ValueError):updates({},'V2_VWAP_PULLBACK','MU','research.1',True,'admin')

    def test_context_and_two_leg_entries_reuse_exact_research_detectors(self):
        from tests.test_context_strategy_observers import _nr7_frame, _vwap_displacement_frame
        from tests.test_two_leg_execution import _bars, _bearish_bars
        from trading import context_research_entries, two_leg_research
        for source,make in [('CTX_ORB_NR7_OR_INSIDE',_nr7_frame),('CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG',_vwap_displacement_frame)]:
            tape,_=make();now=tape.iloc[-1]['time']+timedelta(minutes=1)
            sid='APPROVED_'+source
            with patch.object(context_research_entries,'_last_trigger',{}),patch.object(research_orders,'_emitted',{}):
                expected=context_research_entries.evaluate(tape,strategy_id=source,ticker='MU',scope='research_worker:test',now=now)
                actual=research_orders.evaluate(tape,'MU',execution_scope='orders',now=now,strategy_id=sid)
                self.assertIsNotNone(expected);self.assertIsNotNone(actual)
                self.assertEqual(expected.direction,actual.direction)
                for k,v in expected.meta.items():
                    if k not in ('observation_only',):self.assertEqual(v,actual.meta[k],k)
        for make in (_bars,_bearish_bars):
            tape=make();now=tape.iloc[-1]['time']+timedelta(minutes=1)
            sid='APPROVED_V2_TSLA_TWO_LEG_TREND_PULLBACK'
            with patch.object(research_orders,'_episode_state',{}),patch.object(research_orders,'_emitted',{}):
                expected,_=two_leg_research.update({},tape,ticker='MU',scope='research_worker:test',now=now)
                actual=research_orders.evaluate(tape,'MU',execution_scope='orders',now=now,strategy_id=sid)
                self.assertIsNotNone(actual)
                self.assertEqual(expected.meta['v2_stop'],actual.meta['v2_stop'])
                self.assertEqual(expected.trigger_bar,actual.trigger_bar)

    def test_retouch_only_runs_for_explicitly_approved_ticker_and_deduplicates(self):
        from tests.test_orb_retouch_research import bars,quote
        from trading.entry.injected_setups import evaluate_injected_setups
        from unittest.mock import Mock
        sid='APPROVED_V2_ORB_PULLBACK';now=pd.Timestamp('2026-01-02 09:47:12',tz='America/New_York')
        settings={'paper_trading':True,'active_broker_account_id':'a'}
        settings.update(updates(settings,'V2_ORB_PULLBACK','MU',SPECS[sid].version,True,'admin'))
        broker=Mock();broker.get_latest_quote.return_value=quote('2026-01-02 09:47:12')
        state={}
        with patch('trading.entry.injected_setups._now_et',return_value=now),patch('trading.entry.injected_setups.record_underlying_quote'):
            first=evaluate_injected_setups(state,bars(),'MU',{sid},set(),broker,settings)[0]
            self.assertEqual(1,len(first));self.assertEqual(sid,first[0].strategy_id)
            self.assertFalse(first[0].meta['observation_only'])
            self.assertEqual([],evaluate_injected_setups(state,bars(),'MU',{sid},set(),broker,settings)[0])
            self.assertEqual([],evaluate_injected_setups({},bars(),'QQQ',{sid},set(),broker,settings)[0])
        broker.submit_order.assert_not_called()

    def test_new_timers_and_session_close_work_without_quotes_and_frozen_selection(self):
        from tests.test_research_order_execution import position
        from trading.research_order_exit import evaluate_exit
        from config.research_pair_policy import build
        entry=datetime(2026,9,10,10,5,1)
        for sid,spec in SPECS.items():
            if not sid.startswith('APPROVED_'):continue
            trade={**position(sid),'ticker':'MU'}
            self.assertEqual((True,'research_session_close'),evaluate_exit(trade,entry,entry.replace(hour=15,minute=55),None))
            if spec.adapter in ('retouch','two_leg','native_trend','native_fvg'):
                self.assertEqual((False,'hold'),evaluate_exit(trade,entry,entry+timedelta(minutes=spec.reference_minutes-1),None))
                self.assertTrue(evaluate_exit(trade,entry,entry+timedelta(minutes=spec.reference_minutes),None)[0])
            trade={**position(sid,selected_test_policy=build(sid,'MU',spec.version,60,'target_150_250')),'ticker':'MU'}
            self.assertEqual((True,'selected_test_60m'),evaluate_exit(trade,entry,entry+timedelta(minutes=60),None))

    def test_recommendation_freezes_ticker_config_and_does_not_publish_wrong_version(self):
        from strategy_health.pair_recommendations import assess, recommendations, decide
        from tests.test_pair_recommendations import trades
        from config.strategy_ticker_recommendations import publish_qualified_recommendation
        from strategies.base import Signal
        source='V2_OPENING_MOMENTUM_RTH_EXPLORATORY';version='research.1';sid='APPROVED_'+source
        evidence=assess(trades([20,20,-10,20,-10]*4))
        matrix={'strategies':[{'strategy_id':source,'version':version,'display_name':'Opening Momentum',
                 'pairs':[{'ticker':'MU','tradable':False,'recommendation':evidence}]}]}
        settings={'paper_trading':True,'active_broker_account_id':'account-a'}
        self.assertTrue(recommendations(matrix,settings)['recommendations'][0]['can_enable'])
        saved={**settings,**decide(matrix,settings,sid,'MU','enable',evidence['fingerprint'])}
        with patch('config.get_settings',return_value=saved):
            signal=research_orders.finalize(Signal(strategy_id=source,direction='bullish',confidence=.7,rvol=0,trigger_bar=datetime(2026,9,10,10)),sid,'MU')
        frozen=signal.meta['approved_ticker_config']
        self.assertEqual('MU',frozen['ticker']);self.assertEqual(source,frozen['source_strategy_id'])
        for grant in saved['strategy_pair_approvals'].values():grant['ticker_config']['ticker']='OTHER'
        self.assertEqual('MU',frozen['ticker'])
        with patch('config.strategy_ticker_recommendations.publish_recommendation') as publish:
            publish_qualified_recommendation(dict(decision='qualified',strategy_id=source,strategy_version=version,ticker='MU'),evidence_artifact='test-only')
            self.assertEqual((sid,'MU'),publish.call_args.args)
            with self.assertRaises(ValueError):
                publish_qualified_recommendation(dict(decision='qualified',strategy_id=source,strategy_version='wrong',ticker='MU'),evidence_artifact='test-only')
            self.assertEqual(1,publish.call_count)

    def test_retired_cannot_be_reactivated_implicitly(self):
        source='V2_OPENING_MOMENTUM_RTH_EXPLORATORY';version='research.1'
        settings={'retired_strategy_versions':[source+':'+version]}
        self.assertFalse(capability(settings,source,'MU',version)['ready'])
        with self.assertRaisesRegex(ValueError,'retired'):updates(settings,source,'MU',version,True,'admin')

    def test_new_native_deadlines_match_execution_and_do_not_claim_structural_protection(self):
        from trading.entry.exit_deadline import capture_policy,freeze_at_fill
        from tests.test_research_order_execution import position
        from risk.protection import monitored_risk_fields
        from zoneinfo import ZoneInfo
        now=datetime(2026,9,10,10,tzinfo=ZoneInfo('America/New_York'))
        for sid,spec in SPECS.items():
            if spec.adapter not in ('native_trend','native_fvg','retouch','two_leg'):continue
            with patch('trading.research_session_clock.session_close_if_open',return_value=now.replace(hour=16)):
                plan=capture_policy(sid,None,now)
            actual=freeze_at_fill(plan,now+timedelta(seconds=2))
            self.assertEqual((now+timedelta(seconds=2,minutes=spec.reference_minutes)).isoformat(),actual['exit_deadline'])
            self.assertEqual((),monitored_risk_fields(position(sid,underlying_stop=100),branch='reviewed'))

    def test_preflight_api_is_read_only_and_requires_admin(self):
        from api.routes.settings import get_activation_capability
        from types import SimpleNamespace
        from fastapi import HTTPException
        with patch('config.get_settings',return_value={}),patch('config.save_settings') as save:
            with self.assertRaises(HTTPException):
                get_activation_capability('V2_VWAP_PULLBACK','MU','research.1',SimpleNamespace(state=SimpleNamespace(is_admin=False)))
            result=get_activation_capability('V2_VWAP_PULLBACK','MU','research.1',SimpleNamespace(state=SimpleNamespace(is_admin=True)))
            self.assertTrue(result['ready']);save.assert_not_called()

    def test_extended_library_entry_and_exit_state_match_research_on_real_candles(self):
        import importlib,math
        cases=[('V2_EMA_PULLBACK_RTH','ema',(1,1)),('V2_FAIR_VALUE_GAP','fvg',(1,1)),
               ('V2_MIDDAY_BREAKDOWN','midday',(1,)),('V2_ORB_CONFIRMED_BREAKOUT','orb',(1,1)),
               ('V2_RANGE_SWEEP_RECLAIM','range_sweep',(1,)),('V2_TURTLE_SOUP_RTH','turtle',(1,1)),
               ('V2_VWAP_REVERSION_RTH','reversion',(1,1)),('V2_VWAP_PULLBACK','vwap',(1,1))]
        fixtures=[]
        for source,module,args in cases:
            fixtures.append((source,importlib.import_module('tests.test_'+module+'_exit_measurement').setup_bars(*args)))
        start=datetime(2026,9,10,9,30);bars=[]
        for i in range(50):
            c=100+12*math.sin(i/4);prior=bars[-1].close if bars else c
            bars.append(Bar(start+timedelta(minutes=5*i),prior,max(prior,c)+.4,min(prior,c)-.4,c,100))
        fixtures.append(('TV_SUPERTREND_REVERSAL_V4',bars))
        fixtures.append(('V2_TREND_CONT',[Bar(start+timedelta(minutes=5*i),100+i*.3,100+i*.3+.1,100+i*.3-.1,100+i*.3,500) for i in range(35)]))
        for source,bars in fixtures:
            with self.subTest(source=source):
                engine=TESTED_RESEARCH_STRATEGIES[source].factory();seen=[];candidate=None
                for bar in bars:
                    seen.append(bar);candidate=engine.evaluate(seen)
                    if candidate is not None:break
                self.assertIsNotNone(candidate,'fixture must trigger '+source)
                spec=TESTED_RESEARCH_STRATEGIES[source];tf=spec.timeframe_minutes
                tape=pd.DataFrame([dict(time=b.timestamp+timedelta(minutes=i),open=b.open,high=b.high,low=b.low,close=b.close,volume=b.volume/tf) for b in seen for i in range(tf)])
                now=seen[-1].timestamp+timedelta(minutes=tf)
                with patch('database.load_scanner_candles',return_value=pd.DataFrame()),patch('trading.tested_strategy_research._emitted',set()),patch.object(research_orders,'_emitted',{}):
                    expected=evaluate_tested_research(tape,'MU',[source],scope='test',now=now)
                    actual=research_orders.evaluate(tape,'MU',execution_scope='orders',now=now,strategy_id='APPROVED_'+source)
                    self.assertEqual(1,len(expected));self.assertIsNotNone(actual)
                    self.assertEqual(expected[0].direction,actual.direction)
                    self.assertEqual(expected[0].trigger_bar,actual.trigger_bar)
                    for key in ('underlying_stop','underlying_target','authored_exit_protocol','authored_exit_state'):
                        self.assertEqual(expected[0].meta.get(key),actual.meta.get(key),(source,key))

    def test_squeeze_entry_and_frozen_hourly_exit_state(self):
        from strategies import context_strategy_observers as source
        from strategy_router.indicator_frame import _build_indicator_frame
        from strategy_health.squeeze_exit import metadata
        rows=[];days=pd.bdate_range('2026-09-01',periods=6)
        for index,day in enumerate(days):
            for minute in range(360):
                c=110 if index==5 and minute>=300 else 100
                rows.append(dict(time=day+pd.Timedelta(hours=9,minutes=30+minute),open=c,high=c+1,low=c-1,close=c,volume=100))
        tape=_build_indicator_frame(pd.DataFrame(rows));now=days[-1]+pd.Timedelta(hours=15,minutes=30)
        sid='APPROVED_CTX_1H_SQUEEZE_MACD_LONG'
        with patch.object(source,'_emitted',set()),patch.object(research_orders,'_emitted',{}):
            actual=research_orders.evaluate(tape,'MU',execution_scope='orders',now=now,strategy_id=sid)
        self.assertIsNotNone(actual);self.assertEqual(100.5,actual.meta['sma20'])
        self.assertEqual(metadata(SPECS[sid].source)['authored_exit_protocol'],actual.meta['authored_exit_protocol'])

    def test_new_nr7_partial_order_path_and_recovery_quantity(self):
        from tests.test_research_order_execution import ResearchOrderExecutionTests
        sid='APPROVED_CTX_ORB_NR7_OR_INSIDE'
        # Run the same real manager path with the newly registered NR7 policy.
        # Broker methods are mocked; no network/order authority exists here.
        with patch('tests.test_research_order_execution.ATR10',sid):
            ResearchOrderExecutionTests().test_position_manager_submits_partial_sell_and_full_sell_in_both_modes()
            ResearchOrderExecutionTests().test_partial_quantity_recovery_uses_filled_not_requested_quantity()

    def test_new_timer_manager_exits_without_quote_in_mocked_broker(self):
        from tests.test_failed_range_deadline import FailedRangeDeadlineTests
        from tests.test_research_order_execution import position
        for sid in ('APPROVED_V2_SPY_TREND_CONT','APPROVED_V2_ORB_PULLBACK'):
            trade=position(sid)
            with patch('tests.test_failed_range_deadline.position',return_value=trade):
                broker,market,state=FailedRangeDeadlineTests().run_case('2026-10-14T12:05:28-04:00',ticker='MU')
            self.assertEqual('market',broker.place_option_order.call_args.kwargs['order_type'])
            self.assertEqual('selected_test_'+str(SPECS[sid].reference_minutes)+'m',broker.place_option_order.call_args.kwargs['order_context']['exit_reason'])
            market.get_option_quote.assert_not_called()

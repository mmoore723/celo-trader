import unittest
import json
import sqlite3
from datetime import timedelta
from unittest.mock import patch
from trading.premium_policy import evaluate, freeze_selection, scope, fingerprint
from strategy_health.premium_approval import approve
from strategy_health.premium_research import initialize
from strategy_health.premium_rules import VERSION
from tests.test_premium_rules import T, quote
from tests import test_execution_recovery as recovery
from unittest.mock import Mock


class PremiumExecutionTest(unittest.TestCase):
    def setUp(self):
        self.conn=sqlite3.connect(':memory:')
        self.conn.execute('CREATE TABLE trades(id INTEGER, status TEXT, paper INTEGER, broker_account_id TEXT, strategy_context_json TEXT)')
        self.policy=dict(rule='premium_2pct',version=VERSION,account='A',mode='paper',
                         strategy='TEST',ticker='QQQ',strategy_version='1',approval_id=1)
        self.policy['fingerprint']=fingerprint(self.policy)
        self.trade=dict(id=1,paper=True,broker_account_id='A',strategy_id='TEST',ticker='QQQ',
                        entry_time=T.isoformat(),entry_price=1,contracts=4,contract_symbol='TEST')
        self.conn.execute('INSERT INTO trades VALUES (?,?,?,?,?)',
            (1,'open',1,'A',json.dumps({'premium_exit_policy':self.policy})))

    def tearDown(self):
        self.conn.close()

    def test_native_safety_priority(self):
        self.assertEqual(evaluate(self.conn,self.trade,quote(1.5),T+timedelta(seconds=1),
                                   native_exit=True,native_reason='session_close'),(True,'session_close'))
        state=json.loads(self.conn.execute('SELECT strategy_context_json FROM trades').fetchone()[0])
        self.assertNotIn('premium_exit_state',state)

    def test_persisted_trigger_survives_restart_and_partial_fill(self):
        self.assertEqual(evaluate(self.conn,self.trade,quote(1.02),T+timedelta(seconds=1)),(True,'premium_2pct'))
        self.conn.commit()
        self.trade['contracts']=2
        self.assertEqual(evaluate(self.conn,self.trade,None,T+timedelta(seconds=2)),(True,'premium_2pct'))
        # The outer position manager owns one order intent and retries remaining quantity.
        self.conn.execute("UPDATE trades SET status='closed'")
        self.assertEqual(evaluate(self.conn,self.trade,None,T+timedelta(seconds=3)),(False,'hold'))

    def test_live_and_other_account_never_execute(self):
        for changes in [dict(paper=False),dict(broker_account_id='B')]:
            self.assertEqual(evaluate(self.conn,dict(self.trade,**changes),quote(1.5),T+timedelta(seconds=1)),(False,'hold'))

    def test_unassigned_positions_unchanged(self):
        self.conn.execute("UPDATE trades SET strategy_context_json='{}'")
        self.assertEqual(evaluate(self.conn,self.trade,quote(1.5),T+timedelta(seconds=1)),(False,'hold'))

    def test_freeze_is_copy_scoped_and_never_live(self):
        settings=dict(paper_trading=True,active_broker_account_id='A',premium_exit_paper_assignments={scope('A','TEST','QQQ','1'):self.policy})
        frozen=freeze_selection(settings,'TEST','QQQ','1')
        self.assertEqual(frozen['premium_exit_policy'],self.policy)
        self.assertIsNot(frozen['premium_exit_policy'],self.policy)
        self.assertEqual(freeze_selection(dict(settings,paper_trading=False),'TEST','QQQ','1'),{})
        self.assertEqual(freeze_selection(settings,'TEST','QQQ','2'),{})

    def test_approval_rejects_insufficient_and_live(self):
        initialize(self.conn)
        report=dict(mode='paper',account='A',fingerprint='hash',specification=VERSION,
            candidates=[dict(rule='premium_2pct',evidence_passed=False,gates={})])
        self.conn.execute('INSERT INTO premium_exit_reports VALUES (?,?,?)',('bucket',T.isoformat(),json.dumps(report)))
        with self.assertRaisesRegex(ValueError,'Insufficient'):
            approve(self.conn,dict(paper_trading=True,active_broker_account_id='A'),'bucket','premium_2pct','hash')
        with self.assertRaisesRegex(ValueError,'Only paper'):
            approve(self.conn,dict(paper_trading=False,active_broker_account_id='A'),'bucket','premium_2pct','hash')

    def test_qualified_saved_holdout_to_frozen_paper_policy(self):
        from strategy_health.premium_rules import RULES
        from strategy_health.premium_native import baseline_spec
        from config.strategy_catalog import REVIEWED_STRATEGIES
        sid='V2_SPY_TREND_CONT'; version=REVIEWED_STRATEGIES[sid].version
        settings=dict(paper_trading=True,active_broker_account_id='A')
        rows=[]
        for i in range(100):
            at=T+timedelta(days=i//2)
            rows.append(dict(id=str(i),entry_at=at.isoformat(),exit_at=(at+timedelta(minutes=5)).isoformat(),
                             baseline_net=1,candidate_net=2,prospective=True))
        cutoff=(T+timedelta(days=24)).date().isoformat()
        candidates=[dict(rule=rule,evidence_passed=True,gates={'validated':True},trades=rows,
            attempted=50,selection_attempted=50,selection_complete=True,holdout_started_after=cutoff) for rule in RULES]
        report=dict(mode='paper',account='A',strategy_id=sid,ticker='SPY',strategy_version=version,
                    fingerprint='hash',specification=VERSION,evaluation_closed=True,candidates=candidates,
                    exact_baseline=baseline_spec(settings,sid,'SPY',version))
        initialize(self.conn)
        self.conn.execute('INSERT INTO premium_exit_reports VALUES (?,?,?)',('bucket',T.isoformat(),json.dumps(report)))
        with patch('strategy_health.premium_approval.execution_certified',return_value=True):
            updates,decision=approve(self.conn,settings,'bucket','premium_2pct','hash')
        self.assertEqual(set(updates),{'premium_exit_paper_assignments'})
        frozen=freeze_selection({**settings,**updates},sid,'SPY',version)
        self.assertEqual(frozen['premium_exit_policy'],decision['policy'])
        self.assertEqual(freeze_selection({**settings,**updates,'paper_trading':False},sid,'SPY',version),{})
        self.assertEqual(self.conn.execute('SELECT count(*) FROM premium_exit_decisions').fetchone()[0],1)


class PremiumBrokerPathTests(unittest.TestCase):
    def setUp(self):
        recovery.RecoveryTests.setUp(self)
        self.stack.enter_context(patch('database.connection.get_db_path',return_value=self.path))
    make_client=recovery.RecoveryTests.make_client
    get=recovery.RecoveryTests.get
    post=recovery.RecoveryTests.post
    context=recovery.RecoveryTests.context
    enter=recovery.RecoveryTests.enter
    rows=recovery.RecoveryTests.rows

    def test_three_rules_close_through_real_order_code_with_mocked_transport(self):
        from datetime import datetime
        from trading.position_manager.close import _close_position
        from database import get_conn
        for index,rule in enumerate(('premium_2pct','premium_25pct','giveback_25pct')):
            context=self.context();context['intent_id']=f'premium-{index}'
            policy=dict(version=VERSION,rule=rule,account=recovery.ACCOUNT,mode='paper',
                        strategy='V2_SPY_TREND_CONT',ticker='SPY',strategy_version='2.1.0',approval_id=index+1)
            policy['fingerprint']=fingerprint(policy)
            context['entry_record']['strategy_context_json']=json.dumps({'premium_exit_policy':policy})
            self.next_status,self.next_qty,self.next_price='filled','3','1.60'
            self.enter(context)
            trade=next(t for t in self.rows() if t['status']=='open')
            now=datetime.fromisoformat(recovery.FILL_TIME.replace('Z','+00:00'))+timedelta(seconds=2)
            def q(bid,at):
                return dict(symbol=recovery.SYMBOL,bid=bid,ask=bid+.02,bidsize=10,asksize=10,
                            bid_date=at.timestamp()*1000,ask_date=at.timestamp()*1000)
            with get_conn() as conn:
                if rule=='giveback_25pct':
                    self.assertFalse(evaluate(conn,trade,q(2.,now),now)[0])
                    now+=timedelta(seconds=1)
                    bid=1.90
                else:
                    bid=1.632 if rule=='premium_2pct' else 2.
                self.assertEqual(evaluate(conn,trade,q(bid,now),now),(True,rule))
            self.next_status,self.next_qty,self.next_price='filled','3',str(bid)
            state={'positions':{},'account_balance':4000}
            with patch('trading.position_manager.close.get_user_state',return_value=state), \
                 patch('trading.position_manager.close.get_user_risk',return_value=Mock()), \
                 patch('trading.position_manager.close.get_user_trade_log',return_value=Mock()), \
                 patch('trading.position_manager.close.set_user_trade_log'), \
                 patch('config.atomic_update_json'),patch('database.log_event'), \
                 patch('database.record_paper_option_quote'),patch('database.link_broker_order_to_trade'), \
                 patch('ai_reasoning.narrator.narrate_exit'):
                # A later gap after giveback triggers cannot convert the retry
                # to a market order or allow the broker quote to lower its floor.
                _close_position(self.client,trade,1.50 if rule=='giveback_25pct' else bid,rule,
                    reference_quote=None if rule=='giveback_25pct' else q(bid,now),
                    bid_price=1.49 if rule=='giveback_25pct' else bid)
                if rule=='giveback_25pct':
                    self.assertEqual(self.submissions[-1]['type'],'limit')
                    self.assertGreaterEqual(float(self.submissions[-1]['limit_price']),1.64)
            closed=next(t for t in self.rows() if t['id']==trade['id'])
            self.assertEqual(closed['status'],'closed')
            self.assertEqual(closed['exit_reason'],rule)
            self.assertEqual(json.loads(closed['strategy_context_json'])['premium_exit_policy'],policy)
        self.assertEqual(6,len(self.submissions))

    def test_additional_research_rules_cannot_be_approved(self):
        with sqlite3.connect(':memory:') as conn:
            for rule in ('premium_5pct','premium_15pct','premium_20pct','giveback_15pct','giveback_20pct'):
                with self.assertRaisesRegex(ValueError,'research-only'):
                    approve(conn,self.settings,'unused',rule,'unused')

import unittest
from unittest.mock import patch, Mock
from copy import deepcopy
from datetime import datetime, timezone
from config.research_snapshot import research_settings_snapshot
from config.engine_parameters import scope_key, KEY, _sizing
from config.strategy_catalog import REVIEWED_STRATEGIES
from api.sizing_preview import calculate, preview

class SizingPreviewTests(unittest.TestCase):
    def setUp(self):
        self.sid='V2_SPY_TREND_CONT';self.version=REVIEWED_STRATEGIES[self.sid].version
        self.settings={'paper_trading':True,'active_broker_account_id':'test','risk_per_trade':.2,'max_position_dollars_pct':40,'growth_mode':False}
        self.symbol='SPY991231C00600000'
        self.quote={'source_symbol':self.symbol,'bid':1.9,'ask':2,'quote_age_seconds':1,'quote_source':'tradier'}
    def test_engine_fee_and_entry_cushion_math(self):
        with research_settings_snapshot(__import__('auth.context',fromlist=['get_current_user_id']).get_current_user_id(),self.settings),patch('config.COMMISSION_PER_CONTRACT',.65):
            r=calculate(10000,self.quote,self.symbol)
        self.assertEqual(r['maximum_entry'],2.1)
        self.assertEqual(r['contracts'],9)
        self.assertEqual(r['fees_per_contract'],1.3)
        self.assertEqual(r['total_with_fees'],1901.7)
    def test_bad_prices_and_balance_do_not_produce_count(self):
        for q in [None,{},dict(self.quote,quote_age_seconds=121),dict(self.quote,quote_age_seconds=None),dict(self.quote,bid=3),dict(self.quote,ask=0),dict(self.quote,source_symbol='QQQ')]:
            with self.assertRaises(ValueError):calculate(10000,q,self.symbol)
        for value in [0,None,float('nan')]:
            with self.assertRaises(ValueError):calculate(value,self.quote,self.symbol)
    def test_saved_pair_settings_context_and_no_writes_or_orders(self):
        from auth.context import get_current_user_id
        uid=get_current_user_id()
        scope=scope_key(self.settings,self.sid,'SPY',self.version)
        settings={**self.settings,KEY:{scope:{'risk':{'risk_per_trade':.1,'max_position_dollars_pct':40}}}}
        before=deepcopy(settings)
        broker=Mock(spec=['get_account']);broker.get_account.return_value={'equity':10000}
        market=Mock(spec=['get_option_quote']);market.get_option_quote.return_value=self.quote
        with research_settings_snapshot(uid,settings),patch('config.get_api_keys',return_value={'alpaca_api_key':'test','alpaca_secret_key':'test','tradier_market_api_key':'test'}),patch('broker.get_clients',return_value=(broker,market)),patch('config.save_settings') as save,patch('config.COMMISSION_PER_CONTRACT',.65),patch('api.sizing_preview.datetime') as clock:
            clock.strptime=datetime.strptime
            clock.now.return_value=datetime(2026,11,14,tzinfo=timezone.utc)
            # 2099 expiry uses strptime's 1999 pivot, use 2027 instead.
            symbol='SPY271231C00600000';market.get_option_quote.return_value={**self.quote,'source_symbol':symbol}
            r=preview(self.sid,'SPY',self.version,symbol,scope)
            self.assertEqual(r['contracts'],4)
            save.assert_not_called()
        self.assertIsNone(_sizing.get())
        self.assertEqual(before,settings)
    def test_mismatched_scope_fails_before_broker_access(self):
        from auth.context import get_current_user_id
        with research_settings_snapshot(get_current_user_id(),self.settings),patch('broker.get_clients') as clients:
            with self.assertRaises(ValueError):preview(self.sid,'SPY',self.version,self.symbol,'other')
            clients.assert_not_called()
    def test_missing_credentials_and_wrong_ticker_never_use_example_balance(self):
        from auth.context import get_current_user_id
        scope=scope_key(self.settings,self.sid,'SPY',self.version)
        with research_settings_snapshot(get_current_user_id(),self.settings),patch('config.get_api_keys',return_value={}),patch('broker.get_clients') as clients:
            for symbol in ['QQQ271231C00600000','SPY271231C00600000']:
                with self.assertRaises(ValueError):preview(self.sid,'SPY',self.version,symbol,scope)
            clients.assert_not_called()
        self.assertIsNone(_sizing.get())
    def test_route_requires_authenticated_user(self):
        from api.routes.settings import strategy_sizing_preview
        from fastapi import HTTPException
        from types import SimpleNamespace
        with self.assertRaises(HTTPException) as caught:
            strategy_sizing_preview(SimpleNamespace(state=SimpleNamespace()),self.sid,'SPY',self.version,self.symbol,'scope')
        self.assertEqual(caught.exception.status_code,401)

"""Removing the obsolete selector must not change stored exits or user risk."""
from contextlib import ExitStack
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request
from api.models.settings import Settings
from api.routes.settings import get_settings_endpoint,save_settings_endpoint


class ExitSettingsReadonlyTests(unittest.TestCase):
    def setUp(self):
        self.saved=dict(risk_per_trade=.38,risk_pct=38,risk_auto=False,growth_mode=True,
                        max_position_dollars_pct=38,max_concurrent_positions=3,
                        daily_loss_hard_cap_pct=30,max_daily_loss_pct=.1,
                        broker_provider='alpaca',paper_trading=True,watchlist=['SPY'],
                        simplified_exit_mode=False)
        stack=ExitStack();self.addCleanup(stack.close)
        stack.enter_context(patch('config.get_settings',side_effect=lambda:dict(self.saved)))
        self.write=stack.enter_context(patch('config.save_settings',side_effect=self.saved.update))
        stack.enter_context(patch('database.record_strategy_setting_changes'))
        stack.enter_context(patch('trading.state.get_user_state',return_value={}))
        self.request=Request({'type':'http','method':'POST','path':'/','headers':[]})
        self.request.state.user_id='admin'

    def test_both_switch_directions_rejected_without_any_write(self):
        for current in (True,False):
            self.saved['simplified_exit_mode']=current
            payload=get_settings_endpoint().model_copy(update={'simplified_exit_mode':not current,'risk_pct':50})
            with self.assertRaises(HTTPException) as caught:save_settings_endpoint(payload,self.request)
            self.assertEqual(caught.exception.status_code,409)
            self.write.assert_not_called()
            self.assertEqual(self.saved['risk_per_trade'],.38)

    def test_unchanged_exit_round_trip_preserves_manual_risk(self):
        for mode in (False,True):
            self.saved['simplified_exit_mode']=mode
            payload=get_settings_endpoint().model_copy(update={'display_timezone':'UTC'})
            response=save_settings_endpoint(payload,self.request)
            self.assertEqual(response.simplified_exit_mode,mode)
            self.assertEqual(self.saved['simplified_exit_mode'],mode)
            self.assertEqual(self.saved['risk_per_trade'],.38)
            self.assertEqual((38,3,30,.1),tuple(self.saved[k] for k in (
                'max_position_dollars_pct','max_concurrent_positions','daily_loss_hard_cap_pct','max_daily_loss_pct')))

    def test_omitted_flag_does_not_reset_false_to_model_default(self):
        values=get_settings_endpoint().model_dump(exclude={'simplified_exit_mode'})
        response=save_settings_endpoint(Settings(**values),self.request)
        self.assertFalse(response.simplified_exit_mode)
        self.assertFalse(self.saved['simplified_exit_mode'])

    def test_risk_and_daily_loss_remain_user_editable(self):
        payload=get_settings_endpoint().model_copy(update={'risk_auto':False,'risk_pct':25,
                        'max_position_dollars_pct':25,'daily_loss_hard_cap_pct':15})
        save_settings_endpoint(payload,self.request)
        self.assertEqual(self.saved['risk_per_trade'],.25)
        self.assertEqual(self.saved['daily_loss_hard_cap_pct'],15)
        self.assertFalse(self.saved['simplified_exit_mode'])

    def test_strategy_and_research_toggles_remain_editable(self):
        payload=get_settings_endpoint().model_copy(update={'strategy_spy_trend_cont_v2_enabled':False,
                                                           'observe_ctx_orb_atr10_enabled':False})
        save_settings_endpoint(payload,self.request)
        self.assertFalse(self.saved['strategy_spy_trend_cont_v2_enabled'])
        self.assertFalse(self.saved['observe_ctx_orb_atr10_enabled'])


if __name__=='__main__':unittest.main()

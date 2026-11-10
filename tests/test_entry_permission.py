import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from contextlib import ExitStack
from fastapi import HTTPException
from api.routes.bot import entry_permission, set_entry_permission


class EntryPermissionTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.settings = {'paper_trading': True, 'trading_enabled': False}
        self.halt = {'scope':'paper-account','halted':False,'close_pending':False}
        self.request = SimpleNamespace(state=SimpleNamespace(user_id='fixture'))
        self.stack.enter_context(patch('config.get_settings',side_effect=lambda *a,**k:dict(self.settings)))
        self.save = self.stack.enter_context(patch('config.save_settings',side_effect=lambda update,**k:self.settings.update(update)))
        self.stack.enter_context(patch('config.get_maintenance_state',return_value={'maintenance_mode':False}))
        self.stack.enter_context(patch('risk.halt_controls.halt_status',side_effect=lambda:dict(self.halt)))
        self.broker = Mock()
        self.broker.get_account.return_value={'equity':20000,'trading_blocked':False}
        self.stack.enter_context(patch('broker.get_clients',return_value=(self.broker,None)))
        self.stack.enter_context(patch('database.log_event'))
        self.payload={'enabled':True,'paper':True,'scope':'paper-account'}

    def test_explicit_paper_enable_only_changes_entry_switch(self):
        self.assertFalse(entry_permission(self.request)['enabled'])
        self.assertTrue(set_entry_permission(self.request,self.payload).ok)
        self.save.assert_called_once_with({'trading_enabled':True},user_id='fixture')
        self.assertTrue(entry_permission(self.request)['enabled'])

    def test_live_mode_cannot_be_enabled(self):
        self.settings['paper_trading']=False
        with self.assertRaises(HTTPException):set_entry_permission(self.request,self.payload)
        self.save.assert_not_called()

    def test_wrong_account_and_non_boolean_rejected(self):
        for payload in [dict(self.payload,scope='other'),dict(self.payload,enabled='true')]:
            with self.assertRaises(HTTPException):set_entry_permission(self.request,payload)
        self.save.assert_not_called()

    def test_safety_halt_not_cleared(self):
        for key in ['halted','close_pending']:
            self.halt[key]=True
            with self.assertRaises(HTTPException):set_entry_permission(self.request,self.payload)
            self.halt[key]=False
        self.save.assert_not_called()

    def test_maintenance_blocks_resume(self):
        with patch('config.get_maintenance_state',return_value={'maintenance_mode':True}):
            with self.assertRaises(HTTPException):set_entry_permission(self.request,self.payload)
        self.save.assert_not_called()

    def test_broker_error_blocks_resume_but_not_pause(self):
        self.broker.get_account.side_effect=RuntimeError('offline')
        with self.assertRaises(HTTPException):set_entry_permission(self.request,self.payload)
        self.save.assert_not_called()
        self.assertTrue(set_entry_permission(self.request,dict(self.payload,enabled=False)).ok)

    def test_account_change_during_broker_check_rejected(self):
        def changed():
            self.halt['scope']='different-account'
            return {'equity':20000}
        self.broker.get_account.side_effect=changed
        with self.assertRaises(HTTPException):set_entry_permission(self.request,self.payload)
        self.save.assert_not_called()

    def test_auth_required(self):
        with self.assertRaises(HTTPException):entry_permission(SimpleNamespace(state=SimpleNamespace()))

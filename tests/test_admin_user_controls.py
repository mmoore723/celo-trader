from tests.test_customer_learning import CustomerLearningTests
from unittest.mock import patch
from types import SimpleNamespace
from fastapi import Depends, HTTPException
from auth import users
from auth.context import get_current_user_id, set_current_user
from api.routes import admin

class AdminUserControlTests(CustomerLearningTests):
    def setUp(self):
        super().setUp()
        from api.middleware.auth import require_auth
        self.app.include_router(admin.router,dependencies=[Depends(require_auth)])
    def test_admin_updates_access_and_revokes_old_session_without_touching_settings(self):
        user=self.user('target','watch');path=users._DATA/user['user_id']/'settings.json';before=path.read_bytes()
        r=self.request(users.get_user('admin'),'PATCH','/api/admin/users/'+user['user_id'],json={'username':'target','access_profile':'learning','is_admin':False,'disabled':False})
        self.assertEqual(200,r.status_code,r.text)
        self.assertEqual(2,users.get_user(user['user_id'])['session_version'])
        self.assertEqual(before,path.read_bytes())
        self.assertEqual(401,self.request(user,'GET','/api/learning/foundations').status_code)
    def test_member_cannot_manage_other_user(self):
        target=self.user('target');member=self.user('member','trading')
        for method,path,body in [('PATCH','',{'username':'target','access_profile':'trading','is_admin':True}),('GET','/configuration',None),('POST','/configuration',{'revision':'x','changes':{},'confirm_user_id':target['user_id']})]:
            kwargs={'json':body} if body else {}
            self.assertEqual(403,self.request(member,method,'/api/admin/users/'+target['user_id']+path,**kwargs).status_code)
    def test_disable_login_and_last_admin_guard(self):
        target=self.user('target');users.update_account('admin',target['user_id'],username='target',access_profile='watch',is_admin=False,disabled=True)
        with patch.object(users,'_verify_pw',return_value=True):self.assertIsNone(users.authenticate('target','anything'))
        with self.assertRaises(ValueError):users.update_account('admin','admin',username='admin',access_profile='legacy',is_admin=False,disabled=False)
        with self.assertRaises(ValueError):users.update_account(target['user_id'],'admin',username='admin',access_profile='legacy',is_admin=True,disabled=False)
    def test_tiers_preserve_boundaries(self):
        from auth.customer_access import enforce_customer_access
        for tier in ['watch','learning','learning_discord','trading']:
            u=self.user('u-'+tier,tier)
            self.assertEqual(tier,users.get_user(u['user_id'])['access_profile'])
            if tier!='trading':
                with self.assertRaises(HTTPException):enforce_customer_access(u,'POST','/api/settings')
            if tier in ['learning','learning_discord']:enforce_customer_access(u,'GET','/api/learning/course')
    def test_target_context_restored_on_error(self):
        target=self.user('target');set_current_user('admin','admin',True)
        with self.assertRaises(RuntimeError):
            with admin._target_user(target['user_id']):
                self.assertEqual(target['user_id'],get_current_user_id());raise RuntimeError('failure')
        self.assertEqual('admin',get_current_user_id())
    def test_configuration_rejects_stale_revision_and_unknown_fields(self):
        target=self.user('target');req=SimpleNamespace(state=SimpleNamespace(user_id='admin',is_admin=True))
        from api.models import Settings
        current=Settings.model_construct(risk_pct=1).model_dump()
        with patch('api.routes.settings.get_settings_endpoint',return_value=SimpleNamespace(model_dump=lambda:current)),patch('api.routes.settings.save_settings_endpoint') as save,patch('config.get_user_data_dir',return_value=self.root):
            for changes,revision in [({'risk_pct':5},'stale'),({'unknown':True},admin._settings_revision(current))]:
                with self.assertRaises(HTTPException):admin.update_user_configuration(target['user_id'],admin.UserSettingsUpdate(changes=changes,revision=revision,confirm_user_id=target['user_id']),req)
            save.assert_not_called()
    def test_configuration_saves_in_selected_user_context_only(self):
        target=self.user('target');req=SimpleNamespace(state=SimpleNamespace(user_id='admin',is_admin=True))
        from api.models import Settings
        from api.routes.settings import get_settings_endpoint
        with patch('config.get_settings',return_value={}):current=get_settings_endpoint()
        seen=[]
        def save(payload,request):
            seen.append((get_current_user_id(),request.state.user_id,payload))
            return payload
        set_current_user('admin','admin',True)
        with patch('api.routes.settings.get_settings_endpoint',return_value=current),patch('api.routes.settings.save_settings_endpoint',side_effect=save),patch('config.get_user_data_dir',return_value=self.root):
            result=admin.update_user_configuration(target['user_id'],admin.UserSettingsUpdate(changes={'risk_pct':2},revision=admin._settings_revision(current.model_dump()),confirm_user_id=target['user_id']),req)
        self.assertEqual(target['user_id'],seen[0][0]);self.assertEqual(target['user_id'],seen[0][1]);self.assertEqual('admin',get_current_user_id())
        self.assertEqual(2,result['settings']['risk_pct'])
    def test_credential_management_reuses_existing_guards(self):
        from api.routes.settings import CredentialsPayload
        target=self.user('target');req=SimpleNamespace(state=SimpleNamespace(user_id='admin',is_admin=True))
        body=admin.UserCredentialsUpdate(confirm_user_id=target['user_id'],credentials=CredentialsPayload(alpaca_api_key='test-key'))
        set_current_user('admin','admin',True)
        with patch('api.routes.settings.save_credentials',side_effect=HTTPException(409,'Stop the bot first')) as save:
            with self.assertRaises(HTTPException):admin.update_user_credentials(target['user_id'],body,req)
            self.assertEqual(target['user_id'],save.call_args[0][1].state.user_id)
        self.assertEqual('admin',get_current_user_id())

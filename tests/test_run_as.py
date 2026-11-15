import asyncio
from unittest.mock import patch
from types import SimpleNamespace
import httpx
from jose import jwt, JWTError
from auth import users
from auth.security import COOKIE_NAME, JWT_ALGORITHM
from auth.run_as import COOKIE, issue, resolve
from tests.test_customer_learning import CustomerLearningTests, SECRET

class RunAsTests(CustomerLearningTests):
    def setUp(self):
        super().setUp()
        self.extra=patch('auth.run_as.jwt_secret',return_value=SECRET);self.extra.start();self.addCleanup(self.extra.stop)
        self.authsecret=patch('api.routes.auth.jwt_secret',return_value=SECRET);self.authsecret.start();self.addCleanup(self.authsecret.stop)
    def call(self,actor,method,path,support=None,**kw):
        token=jwt.encode({'sub':actor['user_id'],'session_version':actor['session_version']},SECRET,algorithm=JWT_ALGORITHM)
        cookies={COOKIE_NAME:token}
        if support:cookies[COOKIE]=support
        async def go():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),base_url='https://testserver',cookies=cookies) as c:
                return await c.request(method,path,**kw)
        return asyncio.run(go())
    def test_identity_permissions_expiry_and_return(self):
        admin=users.get_user('admin');target=self.user('target','watch')
        before=(users._DATA/target['user_id']/'settings.json').read_bytes()
        started=self.call(admin,'POST','/api/auth/run-as',json={'user_id':target['user_id']},headers={'origin':'https://celotrader.com'})
        self.assertEqual(200,started.status_code,started.text);support=started.cookies[COOKIE]
        me=self.call(admin,'GET','/api/auth/me',support).json()
        self.assertEqual(target['user_id'],me['user_id']);self.assertFalse(me['is_admin']);self.assertFalse(me['terms_accepted'])
        self.assertEqual(403,self.call(admin,'POST','/api/bot/start',support).status_code)
        self.assertEqual(403,self.call(admin,'POST','/api/auth/accept-terms',support).status_code)
        payload=jwt.decode(support,SECRET,algorithms=[JWT_ALGORITHM]);payload['exp']=1
        expired=jwt.encode(payload,SECRET,algorithm=JWT_ALGORITHM)
        self.assertTrue(self.call(admin,'GET','/api/auth/me',expired).json()['support_session']['expired'])
        self.assertEqual(403,self.call(admin,'POST','/api/bot/start',expired).status_code)
        stopped=self.call(admin,'POST','/api/auth/run-as/stop',expired,headers={'origin':'https://celotrader.com'})
        self.assertEqual(200,stopped.status_code);self.assertIn('Max-Age=0',stopped.headers['set-cookie'])
        self.assertEqual(before,(users._DATA/target['user_id']/'settings.json').read_bytes())
    def test_guards_binding_and_revocation(self):
        admin=users.get_user('admin');target=self.user('target','learning');token='primary'
        signed=issue(admin,target,token)
        self.assertEqual(target['user_id'],resolve(admin,token,signed)[0]['user_id'])
        with self.assertRaises(JWTError):resolve(admin,'different',signed)
        with self.assertRaises(ValueError):issue(target,admin,token)
        with self.assertRaises(ValueError):issue(admin,admin,token)
        self.assertEqual(403,self.call(admin,'POST','/api/auth/run-as',json={'user_id':target['user_id']}).status_code)
        self.assertEqual(403,self.call(target,'POST','/api/auth/run-as',json={'user_id':target['user_id']},headers={'origin':'https://celotrader.com'}).status_code)
        users.update_account('admin',target['user_id'],username='target',access_profile='learning',is_admin=False,disabled=True)
        with self.assertRaises(JWTError):resolve(admin,token,signed)
    def test_configuration_save_targets_user_and_rejects_stale_tab(self):
        from fastapi import Depends
        from api.middleware.auth import require_auth
        from api.routes.settings import router
        from auth.context import get_current_user_id
        from config.strategy_catalog import REVIEWED_STRATEGIES
        self.app.include_router(router,dependencies=[Depends(require_auth)])
        admin=users.get_user('admin');target=self.user('engine-owner','legacy')
        store={u['user_id']:{'paper_trading':True,'active_broker_account_id':'account-'+u['user_id'],'sentinel':'preserve'} for u in [admin,target]}
        def read(*args,**kwargs):return dict(store[get_current_user_id()])
        def write(values,*args,**kwargs):store[get_current_user_id()].update(values)
        def folder(*args,**kwargs):return self.root/get_current_user_id()
        started=self.call(admin,'POST','/api/auth/run-as',json={'user_id':target['user_id']},headers={'origin':'https://celotrader.com'})
        support=started.cookies[COOKIE];sid='V2_SPY_TREND_CONT';v=REVIEWED_STRATEGIES[sid].version
        url=f'/api/settings/strategies/{sid}/SPY/configuration'
        with patch('config.get_settings',side_effect=read),patch('config.save_settings',side_effect=write),patch('config.get_user_data_dir',side_effect=folder):
            view=self.call(admin,'GET',url+'?version='+v,support).json()
            body=dict(version=v,scope=view['scope'],revision=view['revision'],entry={'fast_ema':7},risk={},execution={'contract':{'maximum_dte':25},'native_exit':{'hold_minutes':45}})
            self.assertEqual(409,self.call(admin,'PUT',url,support,json=body,headers={'X-Celo-Account-User':'admin'}).status_code)
            saved=self.call(admin,'PUT',url,support,json=body,headers={'X-Celo-Account-User':target['user_id']})
            self.assertEqual(200,saved.status_code,saved.text)
            self.assertEqual(7,next(x['value'] for x in saved.json()['entry'] if x['key']=='fast_ema'))
            self.assertEqual(25,saved.json()['execution']['contract']['maximum_dte'])
            self.assertEqual(45,saved.json()['execution']['native_exit']['hold_minutes'])
            self.assertNotIn('strategy_engine_parameters',store['admin'])
            self.assertEqual('preserve',store[target['user_id']]['sentinel'])
            self.assertEqual(409,self.call(admin,'PUT',url,support,json=body).status_code)
        conn=users.get_db()
        try:
            rows=conn.execute('SELECT actor,target,changes FROM account_audit').fetchall()
            self.assertTrue(any(r[0]=='admin' and r[1]==target['user_id'] and 'engine_configuration_saved' in r[2] for r in rows))
        finally:conn.close()
    def test_websocket_uses_target_and_nested_sessions_are_rejected(self):
        from api.routes.ws import _authenticate_ws
        admin=users.get_user('admin');target=self.user('stream-owner','legacy')
        token=jwt.encode({'sub':admin['user_id'],'session_version':admin['session_version']},SECRET,algorithm=JWT_ALGORITHM)
        support=issue(admin,target,token)
        with patch('api.routes.ws.jwt_secret',return_value=SECRET):
            result=_authenticate_ws(SimpleNamespace(cookies={COOKIE_NAME:token,COOKIE:support}))
            self.assertEqual(target['user_id'],result)
        self.assertEqual(409,self.call(admin,'POST','/api/auth/run-as',support,json={'user_id':target['user_id']},headers={'origin':'https://celotrader.com'}).status_code)

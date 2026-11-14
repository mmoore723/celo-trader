"""Customer access is enforced on the server, independently of UI routes."""
import asyncio
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import httpx
from fastapi import FastAPI, Depends
from jose import jwt
from auth import users
from auth.customer_access import enforce_customer_access
from auth.security import COOKIE_NAME, JWT_ALGORITHM
from api.middleware.auth import require_auth
from api.routes import learning_foundations as lessons

SECRET = 'customer-access-test-secret-at-least-32-characters'
PASSWORD = 'StrongAccess1!'

class CustomerLearningTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        self.paths=patch.multiple(users,_DB_PATH=self.root/'users.db',_DATA=self.root/'users',_ROOT=self.root);self.paths.start()
        self.env=patch.dict(os.environ,{'DASHBOARD_PASSWORD':PASSWORD,'DASHBOARD_PASSWORD_HASH':''});self.env.start()
        self.progress=patch.object(lessons,'DB_PATH',self.root/'progress.db');self.progress.start()
        self.secret=patch('api.middleware.auth.jwt_secret',return_value=SECRET);self.secret.start()
        # Password hashing is not under test here; authentication/session tests cover it.
        self.hash=patch.object(users,'_hash_pw',return_value='test-hash');self.hash.start()
        users.get_db().close()
        self.app=FastAPI();self.app.include_router(lessons.router,dependencies=[Depends(require_auth)])
        from api.routes.auth import router
        self.app.include_router(router)
        @self.app.post('/api/bot/start',dependencies=[Depends(require_auth)])
        def order_control(): return {'unexpected':'executed'}
    def tearDown(self):
        self.hash.stop();self.secret.stop();self.progress.stop();self.env.stop();self.paths.stop();self.tmp.cleanup()
    def user(self,name='learner',profile='learning'):
        return users.create_user(name,PASSWORD,access_profile=profile)
    def request(self,user,method,path,**kwargs):
        token=jwt.encode({'sub':user['user_id'],'session_version':1},SECRET,algorithm=JWT_ALGORITHM)
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),base_url='https://testserver',cookies={COOKIE_NAME:token}) as client:
                return await client.request(method,path,**kwargs)
        return asyncio.run(run())
    def test_invite_profile_survives_registration_and_restart(self):
        token=users.create_invite('admin',24,'learning')
        user=users.create_user_from_invite(token,'learner',PASSWORD)
        self.assertEqual('learning',user['access_profile'])
        self.assertEqual('learning',users.get_user(user['user_id'])['access_profile'])
        with self.assertRaises(ValueError):users.create_user_from_invite(token,'another',PASSWORD)
        with self.assertRaises(ValueError):users.create_invite('admin',24,'legacy')
    def test_old_database_preserves_existing_users_and_defaults_old_invites_to_watch(self):
        conn=sqlite3.connect(self.root/'old.db')
        conn.execute('CREATE TABLE users(id TEXT,username TEXT,pw_hash TEXT,is_admin INTEGER,created_at TEXT)')
        conn.execute("INSERT INTO users VALUES('existing','existing','hash',0,'old')")
        conn.execute('CREATE TABLE invites(token TEXT,created_by TEXT,expires_at TEXT,used_by TEXT,used_at TEXT)')
        users._run_migrations(conn)
        self.assertEqual('legacy',conn.execute('SELECT access_profile FROM users').fetchone()[0]);conn.close()
    def test_customer_cannot_submit_order_or_mutate_settings(self):
        user=self.user()
        self.assertEqual(403,self.request(user,'POST','/api/bot/start').status_code)
        for path in ['/api/settings','/api/trades/close','/api/admin/invite','/api/settings/credentials','/api/signals','/api/backtest/run','/api/learning/coach/ask']:
            with self.assertRaises(Exception) as caught:enforce_customer_access(user,'POST',path)
            self.assertEqual(403,caught.exception.status_code)
    def test_read_access_is_allowlisted_and_learning_does_not_unlock_research(self):
        for profile in ['watch','learning','unknown']:
            user={'is_admin':False,'access_profile':profile}
            for path in ['/api/trades','/api/settings/credentials','/api/learning/examples','/api/bot/status','/api/new-feature']:
                with self.assertRaises(Exception):enforce_customer_access(user,'GET',path)
        for profile in ['watch','learning']:
            enforce_customer_access({'access_profile':profile},'GET','/api/market/bars/QQQ')
        with self.assertRaises(Exception):enforce_customer_access({'access_profile':'watch'},'GET','/api/learning/foundations')
    def test_existing_and_admin_access_preserved(self):
        for user in [{'access_profile':'legacy'},{'is_admin':True,'access_profile':'watch'},{}]:
            enforce_customer_access(user,'POST','/api/bot/start')
        existing=self.user('existing','legacy')
        self.assertEqual(200,self.request(existing,'POST','/api/bot/start').status_code)
    def test_cookie_role_cannot_upgrade_customer(self):
        user=self.user()
        with patch('api.middleware.auth.jwt.decode',return_value={'sub':user['user_id'],'session_version':1,'is_admin':True,'access_profile':'legacy'}):
            self.assertEqual(403,self.request(user,'POST','/api/bot/start').status_code)
    def test_websocket_does_not_expose_account_stream_to_customer(self):
        from api.routes.ws import _authenticate_ws
        user=self.user()
        token=jwt.encode({'sub':user['user_id'],'session_version':1},SECRET,algorithm=JWT_ALGORITHM)
        with patch('api.routes.ws.jwt_secret',return_value=SECRET):
            self.assertIsNone(_authenticate_ws(SimpleNamespace(cookies={COOKIE_NAME:token})))
    def test_learning_saved_progress_is_user_scoped_and_survives_reopen(self):
        first=self.user();second=self.user('other')
        response=self.request(first,'GET','/api/learning/foundations')
        self.assertEqual(200,response.status_code)
        self.assertNotIn('correct',response.json()['lessons'][0])
        self.assertFalse(response.json()['lessons'][0]['progress']['passed'])
        self.assertTrue(self.request(first,'POST','/api/learning/foundations/answer',json={'lesson':'candle','choice':1}).json()['correct'])
        # A subsequent incorrect answer cannot erase an earlier completed lesson.
        self.request(first,'POST','/api/learning/foundations/answer',json={'lesson':'candle','choice':0})
        progress=self.request(first,'GET','/api/learning/foundations').json()['lessons'][0]['progress']
        self.assertEqual({'attempts':2,'passed':True},progress)
        self.assertFalse(self.request(second,'GET','/api/learning/foundations').json()['lessons'][0]['progress']['passed'])
    def test_validation_watch_denial_and_origin_protection(self):
        watch=self.user('watcher','watch');learner=self.user()
        self.assertEqual(403,self.request(watch,'GET','/api/learning/foundations').status_code)
        for body in [{'lesson':'bad','choice':1},{'lesson':'candle','choice':9},{'lesson':'candle','choice':-1}]:
            self.assertEqual(422,self.request(learner,'POST','/api/learning/foundations/answer',json=body).status_code)
        self.assertEqual(403,self.request(learner,'POST','/api/learning/foundations/answer',json={'lesson':'candle','choice':1},headers={'origin':'https://evil.invalid'}).status_code)
    def test_examples_have_valid_candles_and_one_explanation_per_reveal(self):
        for lesson in lessons.LESSONS:
            self.assertEqual(len(lesson['candles']),len(lesson['notes']))
            self.assertLess(lesson['correct'],len(lesson['choices']))
            for o,h,l,c in lesson['candles']:
                self.assertGreaterEqual(h,max(o,c));self.assertLessEqual(l,min(o,c))

if __name__=='__main__':unittest.main()

class LearningCourseTests(CustomerLearningTests):
    def setUp(self):
        super().setUp()
        from api.routes import learning_course
        self.course=learning_course
        self.course_path=patch.object(learning_course,'DB_PATH',self.root/'course.db');self.course_path.start()
        self.app.include_router(learning_course.router,dependencies=[Depends(require_auth)])
    def tearDown(self):
        self.course_path.stop();super().tearDown()
    def test_course_has_complete_content_without_answer_keys(self):
        r=self.request(self.user(),'GET','/api/learning/course');self.assertEqual(200,r.status_code)
        payload=r.json();self.assertEqual(20,len(payload['lessons']));self.assertEqual(10,len({l['unit'] for l in payload['lessons']}))
        self.assertEqual(10,len(payload['final']['questions']))
        for l in payload['lessons']:
            for k in ['teach','example','watch']:self.assertTrue(l[k])
            for q in l['questions']:self.assertNotIn('correct',q);self.assertNotIn('explanation',q)
    def test_course_progress_isolated_and_final_requires_practice(self):
        a=self.user('alice');b=self.user('bob')
        final=[self.course.LESSONS[i]['questions'][0]['correct'] for i in self.course.FINAL_IDS]
        self.assertEqual(409,self.request(a,'POST','/api/learning/course/answer',json={'lesson':'final','choices':final}).status_code)
        for l in self.course.LESSONS:
            correct=l['questions'][0]['correct']
            wrong=(correct+1)%len(l['questions'][0]['choices'])
            r=self.request(a,'POST','/api/learning/course/answer',json={'lesson':l['id'],'choices':[wrong]})
            self.assertFalse(r.json()['passed'])
            r=self.request(a,'POST','/api/learning/course/answer',json={'lesson':l['id'],'choices':[correct]})
            self.assertTrue(r.json()['passed'])
        r=self.request(a,'POST','/api/learning/course/answer',json={'lesson':'final','choices':final});self.assertEqual(100,r.json()['score'])
        with self.course.connect() as conn:
            self.assertTrue(self.course.progress_for(conn,a['user_id'])['final']['passed'])
            self.assertEqual({},self.course.progress_for(conn,b['user_id']))
        self.assertTrue(self.request(a,'GET','/api/learning/course').json()['final']['progress']['passed'])
    def test_course_rejects_invalid_answers_and_watch_access(self):
        a=self.user()
        for body in [{'lesson':'fake','choices':[0]},{'lesson':'lesson-1','choices':[-1]},{'lesson':'lesson-1','choices':[100]},{'lesson':'lesson-1','choices':[0,1]}]:
            self.assertEqual(422,self.request(a,'POST','/api/learning/course/answer',json=body).status_code)
        watch=self.user('watch','watch')
        self.assertEqual(403,self.request(watch,'GET','/api/learning/course').status_code)
        self.assertEqual(403,self.request(watch,'POST','/api/learning/course/answer',json={'lesson':'lesson-1','choices':[1]}).status_code)
        self.assertEqual(403,self.request(a,'POST','/api/bot/start').status_code)

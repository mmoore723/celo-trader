"""Launch paths are isolated from orders, existing settings and internal research."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import FastAPI, Request, HTTPException
import httpx

class TestClient:
    def __init__(self, app): self.app = app
    def request(self, method, path, **kwargs):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://testserver") as client:
                return await client.request(method, path, **kwargs)
        return asyncio.run(run())
    def get(self, path, **kwargs): return self.request("GET", path, **kwargs)
    def post(self, path, **kwargs): return self.request("POST", path, **kwargs)
    def close(self): pass
    def __enter__(self): return self
    def __exit__(self, *args): pass
from api.routes import launch
from api.middleware.auth import require_auth
from api.middleware.research_access import require_research_admin, require_internal_review
from auth.users import _initialize_member_templates


class LaunchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.paths = patch.object(launch, 'DB_PATH', self.root / 'waitlist.db')
        self.paths.start()
        self.app = FastAPI()
        self.app.include_router(launch.router)
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.paths.stop()
        self.tmp.cleanup()

    def join(self, **updates):
        return self.client.post('/api/launch/waitlist', json={
            'email': 'test@example.com', 'interest': 'learning', 'consent': True, **updates})

    def test_durable_deduplicated_signup_and_token_removal(self):
        first = self.join()
        self.assertEqual(200, first.status_code)
        token = first.json()['removal_token']
        second = self.join(email='TEST@example.com')
        self.assertEqual(200, second.status_code)
        self.assertNotIn('removal_token', second.json())
        conn = launch.connect()
        rows = conn.execute('SELECT * FROM waitlist').fetchall()
        conn.close()
        self.assertEqual(1, len(rows))
        self.assertNotEqual(token, rows[0]['removal_hash'])
        self.assertEqual(launch.CONSENT, rows[0]['consent'])
        # New app/client uses the same persisted file, not process memory.
        app = FastAPI(); app.include_router(launch.router)
        with TestClient(app) as client:
            result = client.post('/api/launch/waitlist/remove', json={'token': token})
        self.assertEqual(200, result.status_code)
        conn = launch.connect()
        self.assertEqual(0, conn.execute('SELECT COUNT(*) FROM waitlist').fetchone()[0])
        conn.close()

    def test_validation_origin_and_honeypot(self):
        self.assertEqual(422, self.join(consent=False).status_code)
        self.assertEqual(422, self.join(email='not-email').status_code)
        self.assertEqual(422, self.join(interest='trading').status_code)
        result = self.client.post('/api/launch/waitlist', headers={'origin':'https://evil.example'}, json={'email':'test@example.com','consent':True})
        self.assertEqual(403, result.status_code)
        self.assertEqual(200, self.join(website='spam').status_code)
        self.assertFalse(launch.DB_PATH.exists())

    def test_rate_limit_persists(self):
        for i in range(10):
            self.assertEqual(200, self.join(email=f'test{i}@example.com').status_code)
        self.assertEqual(429, self.join().status_code)
        with patch.object(launch.time, 'time', return_value=launch.time.time()+3601):
            self.assertEqual(200, self.join().status_code)

    def test_list_requires_admin_and_does_not_expose_tokens(self):
        self.join()
        self.assertEqual(401, self.client.get('/api/launch/waitlist').status_code)
        async def member(request: Request): request.state.is_admin = False
        self.app.dependency_overrides[require_auth] = member
        self.assertEqual(403, self.client.get('/api/launch/waitlist').status_code)
        async def admin(request: Request): request.state.is_admin = True
        self.app.dependency_overrides[require_auth] = admin
        result = self.client.get('/api/launch/waitlist').json()
        self.assertEqual(1, result['total'])
        self.assertEqual({'email','interest','created_at'}, set(result['items'][0]))

    def test_new_member_templates_off_and_existing_not_overwritten(self):
        from config.defaults import _DEFAULTS
        from config.strategy_catalog import REVIEWED_STRATEGIES
        with patch('auth.users._DATA', self.root):
            _initialize_member_templates('new')
            path = self.root / 'new/settings.json'
            data = json.loads(path.read_text())
            keys = {k for k in _DEFAULTS if k.startswith(('strategy_', 'observe_')) and k.endswith('_enabled')}
            keys.update(rule.setting_key for rule in REVIEWED_STRATEGIES.values())
            self.assertTrue(keys)
            self.assertTrue(all(data[k] is False for k in keys))
            self.assertEqual([], data['research_strategy_ids'])
            path.write_text('{"existing":true}')
            _initialize_member_templates('new')
            self.assertEqual({'existing':True}, json.loads(path.read_text()))

    def test_research_guard_and_account_scorecard_exception(self):
        request = Request({'type':'http','path':'/api/exit-lab','headers':[]})
        request.state.is_admin = False
        with self.assertRaises(HTTPException): asyncio.run(require_research_admin(request))
        with self.assertRaises(HTTPException): asyncio.run(require_internal_review(request))
        request = Request({'type':'http','path':'/api/strategy-health/scorecard','headers':[]})
        asyncio.run(require_internal_review(request))
        request.state.is_admin = True
        asyncio.run(require_research_admin(request))

    def test_research_feed_is_not_exposed_to_members(self):
        from api.middleware.research_access import scoped_opportunity_feed
        request = Request({'type':'http','path':'/api/signals/opportunities','headers':[], 'query_string':b''})
        request.state.is_admin = False
        self.assertEqual('operational', asyncio.run(scoped_opportunity_feed(request)))
        request = Request({'type':'http','path':'/api/signals/opportunities','headers':[], 'query_string':b'feed=research'})
        request.state.is_admin = False
        with self.assertRaises(HTTPException): asyncio.run(scoped_opportunity_feed(request))
        request.state.is_admin = True
        self.assertEqual('research', asyncio.run(scoped_opportunity_feed(request)))

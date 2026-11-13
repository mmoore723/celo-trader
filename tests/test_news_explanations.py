import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from api import news_explanations as news

class NewsExplanationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = patch.object(news, 'CACHE_PATH', Path(self.tmp.name) / 'cache.db')
        self.path.start()
    def tearDown(self):
        self.path.stop()
        self.tmp.cleanup()
    def test_cache_and_ticker_isolation(self):
        source = {'ticker':'SPY', 'headline':'Headline', 'summary':'Summary'}
        with patch('ai_reasoning.client.call_claude', return_value=SimpleNamespace(text='{"what_happened":"Sales grew.","ticker_meaning":"Demand may help this company, but prices are uncertain."}')):
            news._generate('test', source)
        with news._db() as db:
            row = db.execute('select payload from explanations').fetchone()[0]
        self.assertIn('ready', row)
        with patch.object(news._pool, 'submit') as submit:
            a = [{'headline':'<b>Headline</b>', 'summary':'Summary'}]
            news.explain_news(a, 'SPY')
            news.explain_news(a, 'SPY')
            news.explain_news(a, 'QQQ')
            self.assertEqual(submit.call_count, 2)
            self.assertEqual(submit.call_args.args[2]['ticker'], 'QQQ')
        news._pending.clear()
    def test_failure_is_honest_and_retry_bounded(self):
        with patch('ai_reasoning.client.call_claude', return_value=SimpleNamespace(text='not JSON')):
            news._generate('bad', {'ticker':'QQQ', 'summary':''})
        with news._db() as db:
            row = db.execute('select payload, retry_after from explanations where key="bad"').fetchone()
        self.assertIn('unavailable', row[0])
        self.assertGreater(row[1], news.time.time())
    def test_headline_only_and_cache_reuse(self):
        article = {'headline':'Sales increased', 'summary':''}
        source = {'ticker':'AMZN', **article}
        key = news.hashlib.sha256((news._PROMPT + news.json.dumps(source, sort_keys=True)).encode()).hexdigest()
        with patch('ai_reasoning.client.call_claude', return_value=SimpleNamespace(text='```json\n{"what_happened":"Sales rose.","ticker_meaning":"The headline alone does not explain profits."}\n```')):
            news._generate(key, source)
        with patch.object(news._pool, 'submit') as submit:
            result = news.explain_news([article], 'AMZN')
            submit.assert_not_called()
        self.assertEqual(result[0]['explanation']['basis'], 'headline_only')
        self.assertEqual(result[0]['explanation']['status'], 'ready')

    def test_new_wording_does_not_reuse_old_explanation(self):
        article = {'headline': 'Prices rising', 'summary': ''}
        source = {'ticker': 'SPY', **article}
        old_key = news.hashlib.sha256(('v2:' + news.json.dumps(source, sort_keys=True)).encode()).hexdigest()
        with news._db() as db:
            db.execute('INSERT INTO explanations VALUES (?, ?, ?)', (old_key, '{"status":"ready","what_happened":"Old jargon"}', news.time.time() + 86400))
        with patch.object(news._pool, 'submit') as submit:
            result = news.explain_news([article], 'SPY')
            self.assertEqual(result[0]['explanation']['status'], 'pending')
            submit.assert_called_once()
        news._pending.clear()

import json
import tempfile
import time
import unittest
from pathlib import Path
from strategy_health.exit_lab import publish, read, bucket_id


def summary(**changes):
    return dict(strategy='test', ticker='SPY', version='v1', revision='sha1',
                status='awaiting approval', recommendation='INSUFFICIENT EVIDENCE',
                result_kind='hypothetical shadow', **changes)


class ExitLabTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'lab.db'

    def test_empty_read_does_not_create_database(self):
        self.assertEqual(read(self.path, 'a', 'paper')['buckets'], [])
        self.assertFalse(self.path.exists())

    def test_scope_isolation_including_guessed_id(self):
        identity = publish(self.path, 'a', 'paper', summary(), {'rules': 'private'}, [{'id': 1}])
        self.assertIsNone(read(self.path, 'b', 'paper', identity))
        self.assertIsNone(read(self.path, 'a', 'live', identity, page=1))
        self.assertEqual(read(self.path, 'b', 'paper')['buckets'], [])
        self.assertNotEqual(identity, bucket_id('a','live','test','SPY','v1','sha1'))

    def test_read_only_and_pagination(self):
        identity = publish(self.path,'a','paper',summary(), {'rules': []}, [{'id':i} for i in range(101)])
        before = self.path.read_bytes()
        self.assertEqual(len(read(self.path,'a','paper',identity,page=1)['rows']),50)
        self.assertTrue(read(self.path,'a','paper',identity,page=2)['has_more'])
        self.assertEqual(read(self.path,'a','paper',identity,page=3)['rows'],[{'id':100}])
        self.assertFalse(read(self.path,'a','paper',identity,page=3)['has_more'])
        self.assertEqual(before,self.path.read_bytes())

    def test_unverified_is_not_matched(self):
        publish(self.path,'a','paper',summary(), {})
        self.assertEqual(read(self.path,'a','paper')['buckets'][0]['policy_match'],'UNVERIFIED')
        publish(self.path,'a','paper',summary(paper_policy='p1',live_policy='p1'), {})
        self.assertEqual(read(self.path,'a','paper')['buckets'][0]['policy_match'],'MATCHED')
        publish(self.path,'a','paper',summary(paper_policy='p1',live_policy='p2'), {})
        self.assertEqual(read(self.path,'a','paper')['buckets'][0]['policy_match'],'MISMATCH')

    def test_republish_atomic_replace_and_json_validation(self):
        identity=publish(self.path,'a','paper',summary(), {},[{'id':1}])
        with self.assertRaises(ValueError):
            publish(self.path,'a','paper',summary(), {},[{'value':float('nan')}])
        self.assertEqual(read(self.path,'a','paper',identity,page=1)['rows'],[{'id':1}])
        publish(self.path,'a','paper',summary(), {},[{'id':2}])
        self.assertEqual(read(self.path,'a','paper',identity,page=1)['rows'],[{'id':2}])

    def test_summary_never_returns_trade_payloads(self):
        publish(self.path,'a','paper',summary(),{'secret_detail':'detail'},[{'secret_trade':'trade'}])
        self.assertNotIn('secret',json.dumps(read(self.path,'a','paper')))

    def test_no_order_or_worker_calls_in_http_routes(self):
        import ast
        source=Path('api/routes/exit_lab.py').read_text()
        tree=ast.parse(source)
        names={n.func.id for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)}
        self.assertFalse(names & {'publish','seed_inventory','submit_order','backtest'})
        self.assertNotIn('@router.post',source)

    def test_cached_summary_read_cost(self):
        for i in range(15):
            row=summary();row['ticker']=f'T{i}'
            publish(self.path,'a','paper',row,{},[{'id':i}]*1000)
        started=time.perf_counter()
        for _ in range(100):
            self.assertEqual(len(read(self.path,'a','paper')['buckets']),15)
        elapsed=time.perf_counter()-started
        print(f'Exit Lab 100 summary reads / 15 buckets / 15000 details: {elapsed:.3f}s')
        self.assertLess(elapsed,5)


if __name__=='__main__':
    unittest.main()

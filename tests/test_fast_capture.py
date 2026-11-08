import json
from datetime import datetime,timedelta,timezone
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from strategy_health.fast_capture import Registry,discover,capture_horizon,sessions,ET,scope_key

NOW=datetime(2026,11,9,10,0,tzinfo=ET).astimezone(timezone.utc)
SYMBOL='SPY261120C00600000'


class FastCaptureTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); self.r=Registry(self.root)
        self.addCleanup(self.r.db.close)

    def add(self,**changes):
        args=dict(account='paper-a',mode='paper',strategy='strategy',ticker='SPY',version='v1',symbol=SYMBOL,
            entry_at=(NOW-timedelta(seconds=30)).isoformat(),until_at=(NOW+timedelta(hours=2)).isoformat(),
            origin='research_selection',origin_id='one',policy='native-v1',metadata={'level':100},now=NOW)
        args.update(changes); return self.r.register(**args)

    def quote(self,symbol=SYMBOL,now=NOW):
        return dict(symbol=symbol,bid=1,ask=1.1,bidsize=5,asksize=6,
                    bid_date=now.timestamp()*1000,ask_date=now.timestamp()*1000,greeks={'delta':.5})

    def test_scope_and_version_isolation_with_shared_raw_quote(self):
        ids={self.add(),self.add(account='paper-b'),self.add(mode='live'),self.add(version='v2')}
        self.assertEqual(4,len(ids)); self.assertEqual([SYMBOL],self.r.due(NOW))
        self.r.record([SYMBOL],{'quotes':{'quote':self.quote()}},NOW,NOW)
        self.assertEqual(4,self.r.db.execute('SELECT count(*) FROM links').fetchone()[0])
        self.assertEqual(1,self.r.db.execute('SELECT count(*) FROM observations').fetchone()[0])
        report=self.r.health(NOW)
        self.assertEqual(2,len(report[scope_key('paper-a','paper')]))
        self.assertEqual(1,len(report[scope_key('paper-b','paper')]))

    def test_restart_idempotence_preserves_metadata_and_extends_horizon(self):
        identity=self.add(); original=dict(self.r.db.execute('SELECT * FROM registrations').fetchone())
        reopened=Registry(self.root)
        try:
            self.assertEqual([SYMBOL],reopened.due(NOW))
        finally: reopened.db.close()
        self.assertEqual(identity,self.add(metadata={'level':200},until_at=(NOW+timedelta(hours=3)).isoformat()))
        row=dict(self.r.db.execute('SELECT * FROM registrations').fetchone())
        self.assertEqual(original['metadata'],row['metadata'])
        self.assertEqual(original['registered_at'],row['registered_at'])
        self.assertEqual(1,self.r.db.execute('SELECT count(*) FROM events').fetchone()[0])

    def test_more_than_batch_limit_fair_batches_no_exclusions(self):
        for i in range(601): self.add(symbol=f'SPY261120C{600000+i:08}',origin_id=str(i))
        seen=set()
        for i in range(3):
            now=NOW+timedelta(seconds=i*5); batch=self.r.due(now); seen.update(batch)
            self.r.record(batch,{'quotes':{'quote':[self.quote(s,now) for s in batch]}},now,now)
        self.assertEqual(601,len(seen))
        self.assertEqual(601,self.r.db.execute('SELECT count(*) FROM registrations').fetchone()[0])

    def test_expired_contract_preserved_but_not_polled(self):
        expired='SPY261106C00600000'
        self.add(symbol=expired)
        self.add()
        self.assertEqual([SYMBOL],self.r.due(NOW))
        self.assertEqual(2,self.r.db.execute('SELECT count(*) FROM registrations').fetchone()[0])
        b=self.r.health(NOW)[scope_key('paper-a','paper')][0]
        self.assertIn('contract_expired_no_further_polling_records_preserved',b['errors'])
        self.assertEqual(1,b['pending'])
        self.assertEqual(1,b['late'])

    def test_expiration_date_kept_through_eastern_day(self):
        self.add(symbol='SPY261109C00600000')
        self.assertEqual(1,len(self.r.due(NOW)))

    def test_failure_checkpoint_and_bounded_retry(self):
        self.add(); self.r.fail([SYMBOL],NOW,'provider_http_429')
        self.assertEqual([],self.r.due(NOW+timedelta(seconds=9)))
        self.assertEqual([SYMBOL],self.r.due(NOW+timedelta(seconds=10)))
        reopened=Registry(self.root)
        try: self.assertEqual('provider_http_429',reopened.db.execute('SELECT error FROM polling').fetchone()[0])
        finally: reopened.db.close()
        for i in range(10): self.r.fail([SYMBOL],NOW,'timeout')
        self.assertEqual(NOW.timestamp()+300,self.r.db.execute('SELECT next_at FROM polling').fetchone()[0])

    def test_invalid_prices_and_missing_contracts_remain_observations(self):
        self.add(); raw=self.quote(); raw['bid_date']=0
        self.r.record([SYMBOL],{'quotes':{'quote':raw}},NOW,NOW)
        self.assertEqual('stale_or_future_quote',self.r.db.execute('SELECT validation FROM observations').fetchone()[0])
        later=NOW+timedelta(seconds=20)
        self.r.record([SYMBOL],{},later,later)
        row=self.r.db.execute('SELECT * FROM polling').fetchone()
        self.assertEqual(1,row['gaps_over_10']); self.assertEqual(20,row['max_gap'])
        self.assertIn('missing_provider_quote',self.r.db.execute('SELECT payload FROM observations ORDER BY received_at DESC').fetchone()[0])

    def test_duplicate_event_does_not_duplicate_gap_or_links(self):
        self.add()
        for _ in range(2): self.r.record([SYMBOL],{'quotes':{'quote':self.quote()}},NOW,NOW)
        self.assertEqual(1,self.r.db.execute('SELECT count(*) FROM observations').fetchone()[0])
        self.assertEqual(1,self.r.db.execute('SELECT count(*) FROM links').fetchone()[0])
        with self.assertRaisesRegex(ValueError,'duplicate_contract'):
            self.r.record([SYMBOL],{'quotes':{'quote':[self.quote(),self.quote()]}},NOW,NOW)

    def test_new_registration_does_not_claim_prior_shared_quotes(self):
        self.add()
        self.r.record([SYMBOL],{'quotes':{'quote':self.quote()}},NOW,NOW)
        self.add(account='later-account',now=NOW+timedelta(seconds=1))
        b=self.r.health(NOW+timedelta(seconds=1))[scope_key('later-account','paper')][0]
        self.assertIsNone(b['last_collection']); self.assertEqual(1,b['pending'])

    def test_calendar_early_close_and_explicit_later_candidate_horizon(self):
        cal=sessions({'calendar':{'days':{'day':[
            {'date':'2026-11-09','status':'open','open':{'start':'09:30','end':'13:00'}},
            {'date':'2026-11-10','status':'open','open':{'start':'09:30','end':'16:00'}}]}}})
        until=capture_horizon(NOW,cal,{})
        self.assertEqual('2026-11-10T21:01:00+00:00',until.isoformat())
        later='2026-11-11T21:00:00+00:00'
        self.assertEqual('2026-11-11T21:01:00+00:00',capture_horizon(NOW,cal,{'candidate_exit_deadline':later}).isoformat())
        with self.assertRaises(ValueError): capture_horizon(NOW,cal[:1],{})

    def test_discovery_read_only_account_scoped_and_hypothetical_label(self):
        path=self.root/'source.db'; c=sqlite3.connect(path)
        c.executescript('''CREATE TABLE shadow_candidates(candidate_id TEXT,ticker TEXT,strategy_id TEXT,
            metadata_json TEXT,broker_account_id TEXT,observed_at TEXT);
            CREATE TABLE candidate_option_quote_observations(candidate_id TEXT,observation_kind TEXT,contract_symbol TEXT,observed_at TEXT);''')
        for account in ('paper-a','paper-b'):
            c.execute('INSERT INTO shadow_candidates VALUES (?,?,?,?,?,?)',(account,'SPY','strategy',json.dumps({'strategy_version':'v1','authored_exit_protocol':'native-v1'}),account,NOW.isoformat()))
            c.execute('INSERT INTO candidate_option_quote_observations VALUES (?,?,?,?)',(account,'entry',SYMBOL,NOW.isoformat()))
        c.commit(); c.close(); before=path.read_bytes()
        cal=[(NOW.replace(hour=14,minute=30),NOW.replace(hour=21)),(NOW.replace(hour=14,minute=30)+timedelta(days=1),NOW.replace(hour=21)+timedelta(days=1))]
        report=discover(path,'paper-a','paper',self.r,cal,NOW)
        self.assertEqual(1,report['registered']); self.assertEqual({},report['blocked'])
        self.assertEqual(before,path.read_bytes())
        row=self.r.db.execute('SELECT * FROM registrations').fetchone()
        self.assertEqual('paper-a',row['account']); self.assertEqual('research_selection',row['origin'])
        self.assertIn('not_verified_entry_state',row['metadata'])

    def test_missing_version_does_not_silently_drop_capture(self):
        self.add(version=None,policy=None)
        self.assertEqual([SYMBOL],self.r.due(NOW))
        self.assertEqual(['missing_version_or_policy'],self.r.health(NOW)[scope_key('paper-a','paper')][0]['missing_inputs'])

    def test_alternatives_and_expiration_studies_are_not_silently_excluded(self):
        path=self.root/'studies.db'; c=sqlite3.connect(path)
        c.executescript('''CREATE TABLE shadow_candidates(candidate_id TEXT,ticker TEXT,strategy_id TEXT,
            metadata_json TEXT,broker_account_id TEXT,observed_at TEXT);
            CREATE TABLE candidate_contract_alternatives(candidate_id TEXT,observation_kind TEXT,contract_symbol TEXT,observed_at TEXT);
            CREATE TABLE research_expiration_comparisons(candidate_id TEXT,profile_version TEXT,state_json TEXT);''')
        c.execute('INSERT INTO shadow_candidates VALUES (?,?,?,?,?,?)',('id','SPY','strategy',json.dumps({'strategy_version':'v1','authored_exit_protocol':'p'}),'a',NOW.isoformat()))
        c.execute('INSERT INTO candidate_contract_alternatives VALUES (?,?,?,?)',('id','entry',SYMBOL,NOW.isoformat()))
        c.execute('INSERT INTO research_expiration_comparisons VALUES (?,?,?)',('id','profile-v1',json.dumps({'contract_symbol':SYMBOL,'entry_quote_at':NOW.isoformat()})))
        c.execute('INSERT INTO research_expiration_comparisons VALUES (?,?,?)',('id','bad-profile','invalid-json'))
        c.commit(); c.close()
        cal=[(NOW,NOW+timedelta(hours=6)),(NOW+timedelta(days=1),NOW+timedelta(days=1,hours=6))]
        result=discover(path,'a','paper',self.r,cal,NOW)
        self.assertEqual(2,result['registered']); self.assertEqual(1,sum(result['blocked'].values()))
        self.assertEqual({'source_contract_missing':1},result['blocked'])
        self.assertEqual({'research_alternative','research_expiration_study'},
                         {r[0] for r in self.r.db.execute('SELECT origin FROM registrations')})

    def test_stale_registration_is_not_polled_and_invalid_scope_rejected(self):
        self.add(until_at=(NOW-timedelta(seconds=1)).isoformat())
        self.assertEqual([],self.r.due(NOW))
        with self.assertRaises(ValueError): self.add(account='')
        with self.assertRaises(ValueError): self.add(symbol='bad')
        with self.assertRaises(ValueError): self.add(entry_at='2026-11-09T10:00:00')

    def test_main_once_offline_writes_health_without_experiment_or_orders(self):
        import strategy_health.fast_capture as module
        from unittest.mock import Mock
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None): return NOW.astimezone(tz or timezone.utc)
        feed=Mock(next_request=0)
        feed.get.return_value=({'calendar':{'days':{'day':[
            {'date':'2026-11-09','status':'open','open':{'start':'09:30','end':'16:00'}},
            {'date':'2026-11-10','status':'open','open':{'start':'09:30','end':'16:00'}}]}}},NOW)
        with patch.object(module,'datetime',Clock),patch.object(module,'Feed',return_value=feed),\
             patch('config.get_settings',return_value={'active_broker_account_id':'a','paper_trading':True}),\
             patch('config.get_api_keys',return_value={'tradier_market_api_key':'offline'}),\
             patch('config.get_user_data_dir',return_value=self.root),patch('auth.context.set_current_user'),\
             patch('sys.argv',['capture','--user','offline','--once']):
            module.main()
        report=json.loads((self.root/'fast_capture_health.json').read_text())
        self.assertFalse(report['experiment_evaluation_started'])
        self.assertEqual({'missing_source_database':1},report['discovery']['blocked'])
        self.assertEqual(2,feed.get.call_count)  # Current and prior month for ten-day discovery.
        self.assertTrue(all(call.args[0]=='calendar' for call in feed.get.call_args_list))

    def test_api_saved_summary_scope_and_no_side_effects(self):
        from api.routes.session_capture import fast_coverage
        report=dict(heartbeat_at=datetime.now(timezone.utc).isoformat(),status='collecting',batch_size=20,request_interval_seconds=5,
            scopes={scope_key('a','paper'):[{'ticker':'SPY'}],scope_key('b','paper'):[{'ticker':'QQQ'}]})
        path=self.root/'fast_capture_health.json'; path.write_text(json.dumps(report)); before=path.read_bytes()
        with patch('api.routes.session_capture.get_user_data_dir',return_value=self.root),patch('config.get_settings',return_value={'active_broker_account_id':'a','paper_trading':True}):
            out=fast_coverage(); self.assertEqual([{'ticker':'SPY'}],out['buckets']); self.assertFalse(out['experiment_evaluation_started'])
        self.assertEqual(before,path.read_bytes())


if __name__=='__main__': unittest.main()

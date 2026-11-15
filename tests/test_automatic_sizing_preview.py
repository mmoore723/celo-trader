import unittest, tempfile, sqlite3, json
from pathlib import Path
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
from api.sizing_preview import current_candidate, automatic_preview
from config.engine_parameters import scope_key
from config.strategy_catalog import REVIEWED_STRATEGIES
from config.research_snapshot import research_settings_snapshot
from auth.context import get_current_user_id

class AutomaticSizingTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  self.sid='V2_SPY_TREND_CONT';self.version=REVIEWED_STRATEGIES[self.sid].version
  self.settings={'paper_trading':True,'active_broker_account_id':'mine'}
  self.now=datetime.now(timezone.utc)
  self.db=sqlite3.connect(self.root/'trades_paper.db')
  self.addCleanup(self.db.close)
  self.db.execute('CREATE TABLE shadow_candidates(candidate_id TEXT, observed_at TEXT, ticker TEXT, strategy_id TEXT, broker_account_id TEXT, metadata_json TEXT, final_outcome TEXT, linked_trade_id INTEGER)')
  self.patch=patch('config.paths.get_user_data_dir',return_value=self.root);self.patch.start();self.addCleanup(self.patch.stop)
 def row(self,id='a',seconds=0,account='mine',ticker='SPY',sid=None,version=None,status='pending',symbol='SPY271231C00600000',observation=False,missing=False):
  meta={'strategy_version':version or self.version,'observation_only':observation,'manual_plan':{'contract_preview':{'status':'selected','symbol':symbol}}}
  if missing:meta['manual_plan']={}
  self.db.execute('INSERT INTO shadow_candidates VALUES(?,?,?,?,?,?,?,NULL)',(id,(self.now+timedelta(seconds=seconds)).isoformat(),ticker,sid or self.sid,account,json.dumps(meta),status));self.db.commit()
 def read(self,settings=None):return current_candidate(settings or self.settings,self.sid,'SPY',self.version,now=self.now)
 def test_exact_account_ticker_strategy_and_mode(self):
  self.row();self.row('other',account='other');self.row('qqq',ticker='QQQ');self.row('strategy',sid='OTHER')
  self.assertEqual(self.read()[0]['candidate_id'],'a')
  self.assertIsNone(self.read({**self.settings,'paper_trading':False})[0])
 def test_latest_missing_or_stopped_never_falls_back(self):
  self.row(seconds=-30);self.row('new',missing=True)
  self.assertIsNone(self.read()[0])
  self.row('terminal',status='blocked')
  self.assertIn('stopped',self.read()[1])
 def test_stale_future_wrong_version_research_are_unavailable(self):
  for kw in [{'seconds':-121},{'seconds':1},{'version':'old'},{'observation':True}]:
   self.db.execute('DELETE FROM shadow_candidates');self.row(**kw)
   self.assertIsNone(self.read()[0])
 def test_waiting_does_not_fetch_broker_or_send_orders(self):
  scope=scope_key(self.settings,self.sid,'SPY',self.version)
  with research_settings_snapshot(get_current_user_id(),self.settings),patch('api.sizing_preview.preview') as price:
   self.assertEqual(automatic_preview(self.sid,'SPY',self.version,scope)['status'],'waiting');price.assert_not_called()
 def test_newest_candidate_passes_exact_symbol_and_rechecks(self):
  self.row();scope=scope_key(self.settings,self.sid,'SPY',self.version)
  with research_settings_snapshot(get_current_user_id(),self.settings),patch('api.sizing_preview.preview',return_value={'contracts':9}) as price:
   r=automatic_preview(self.sid,'SPY',self.version,scope)
   self.assertEqual(r['status'],'ready');self.assertEqual(r['contracts'],9)
   price.assert_called_once_with(self.sid,'SPY',self.version,'SPY271231C00600000',scope)
 def test_candidate_resolved_during_quote_fetch_hides_quantity(self):
  self.row();scope=scope_key(self.settings,self.sid,'SPY',self.version)
  def price(*args):
   self.db.execute("UPDATE shadow_candidates SET final_outcome='entered'");self.db.commit();return {'contracts':9}
  with research_settings_snapshot(get_current_user_id(),self.settings),patch('api.sizing_preview.preview',side_effect=price):
   r=automatic_preview(self.sid,'SPY',self.version,scope)
   self.assertEqual(r['status'],'waiting');self.assertNotIn('contracts',r)

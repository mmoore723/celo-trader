from unittest.mock import patch

from tests import test_context_orb_exit_capture as shared
from strategy_health import context_orb_exit as module
from strategy_health.authored_exit_summary import load_authored_exits, authored_summary


class Atr10ExitCaptureTests(shared.ContextOrbExitCaptureTests):
    """Run every premium timing, accounting and recovery case on ATR10 too."""
    def seed(self,name='one',**changes):
        super().seed(name,**{**dict(strategy_id=module.ATR10_STRATEGY_ID,protocol=module.ATR10_PROTOCOL,
                         state=module.metadata(module.ATR10_STRATEGY_ID)['authored_exit_state']),**changes})

    def summary(self):
        with self.f.connect() as conn:
            exits=load_authored_exits(conn,'a','2026-09-10')
        return authored_summary([{'candidate_id':'one'}],exits,module.ATR10_PROTOCOL)

    def test_matrix_exposes_separate_one_and_two_contract_results(self):
        self.seed(); self.tick('10:07',4,'10:06:30'); self.f.capture()
        from strategy_health.research_matrix import build_research_matrix
        with patch('database.get_conn',self.f.connect),patch('database._now_et',return_value=self.f.now),patch(
            'config.get_settings',return_value={'active_broker_account_id':'a','observe_ctx_orb_atr10_enabled':True}),patch(
            'scanner.state_io._read_daily_universe',return_value={}):
            matrix=build_research_matrix()
        strategy=next(s for s in matrix['strategies'] if s['strategy_id']==module.ATR10_STRATEGY_ID)
        pair=next(p for p in strategy['pairs'] if p['ticker']=='META')
        self.assertEqual(1,pair['authored_exit_evidence']['option_results'])
        self.assertEqual(393.4,pair['authored_exit_evidence']['partial_exit_comparison']['net_two_contract_pnl'])

    def test_nr7_and_atr_overlaps_share_quote_but_not_proof(self):
        self.seed()
        self.seed('nr7',strategy_id=module.STRATEGY_ID,protocol=module.PROTOCOL,
                  state=module.metadata(module.STRATEGY_ID)['authored_exit_state'])
        self.seed('borrowed',state=module.metadata(module.STRATEGY_ID)['authored_exit_state'])
        self.seed('short')
        with self.f.connect() as conn:
            conn.execute("UPDATE shadow_candidates SET direction='bearish' WHERE candidate_id='short'")
        self.tick('10:07',4,'10:06:30'); self.f.capture()
        rows={r['candidate_id']:r for r in self.f.rows()}
        self.assertEqual('priced',rows['one']['status'])
        self.assertEqual('priced',rows['nr7']['status'])
        self.assertEqual('missing_exit_state',rows['borrowed']['reason'])
        self.assertEqual('invalid_direction',rows['short']['reason'])
        self.f.quote.assert_called_once_with('XYZ')

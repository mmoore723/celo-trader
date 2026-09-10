from tests import test_context_vwap_exit_capture as shared
from strategy_health import context_vwap_exit as exits


class DisplacementExitCaptureTests(shared.ContextVwapCaptureTests):
    strategy_id=exits.DISPLACEMENT_STRATEGY_ID
    protocol=exits.DISPLACEMENT_PROTOCOL
    version='0.2.0'
    setting='observe_ctx_vwap_displacement_enabled'

    def test_both_vwap_strategies_share_quotes_not_proof(self):
        self.seed()
        self.seed('ker',strategy_id=exits.STRATEGY_ID,protocol=exits.PROTOCOL,
                  state=exits.metadata(exits.STRATEGY_ID)['authored_exit_state'])
        self.seed('borrowed',state=exits.metadata(exits.STRATEGY_ID)['authored_exit_state'])
        self.f.capture()
        rows={r['candidate_id']:r for r in self.f.rows()}
        self.assertEqual('priced',rows['one']['status'])
        self.assertEqual('priced',rows['ker']['status'])
        self.assertEqual('missing_exit_state',rows['borrowed']['reason'])
        self.f.quote.assert_called_once_with('XYZ')

    def test_previous_version_does_not_enter_current_matrix_result(self):
        self.seed(); self.f.capture()
        from unittest.mock import patch
        from strategy_health.research_matrix import build_research_matrix
        with self.f.connect() as conn:
            conn.execute("UPDATE shadow_candidates SET metadata_json=json_set(metadata_json,'$.strategy_version','0.1.0')")
        with patch('database.get_conn',self.f.connect),patch('database._now_et',return_value=self.f.now),patch(
            'config.get_settings',return_value={'active_broker_account_id':'a',self.setting:True}),patch(
            'scanner.state_io._read_daily_universe',return_value={}):
            matrix=build_research_matrix()
        strategy=next(s for s in matrix['strategies'] if s['strategy_id']==self.strategy_id)
        pair=next(p for p in strategy['pairs'] if p['ticker']=='META')
        self.assertEqual(0,pair['authored_exit_evidence']['option_results'])

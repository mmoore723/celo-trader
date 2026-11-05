from copy import deepcopy
from unittest import TestCase
from unittest.mock import patch

from config.admin_strategy_overrides import updates
from config.strategy_catalog import REVIEWED_STRATEGIES


class ActivationModeIsolationTests(TestCase):
    def test_pair_permission_does_not_switch_account_or_change_risk(self):
        sid = "V2_SPY_TREND_CONT"
        rule = REVIEWED_STRATEGIES[sid]
        for paper in (True, False):
            with self.subTest(paper=paper):
                settings = {"paper_trading": paper, "risk_per_trade": 0.01,
                            "active_broker_account_id": "test-account"}
                before = deepcopy(settings)
                with patch("config.strategy_catalog.reviewed_strategy_integrity_errors", return_value={}), \
                        patch("strategy_health.closed_trade_guard.is_paused", return_value=False):
                    changes = updates(settings, sid, "SPY", rule.version, True, "admin")
                self.assertEqual(settings, before)
                self.assertEqual(set(changes), {"admin_strategy_overrides", "strategy_pair_pauses", rule.setting_key})
                combined = {**settings, **changes}
                self.assertEqual(combined["paper_trading"], paper)
                self.assertEqual(combined["risk_per_trade"], 0.01)
                self.assertEqual(combined["active_broker_account_id"], "test-account")

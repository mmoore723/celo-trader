import unittest

from trading.v2_orb_execution_profile import uses_v2_orb_execution_profile


class V2OrbExecutionProfileTests(unittest.TestCase):
    def test_strategy_identity_is_mode_independent(self) -> None:
        self.assertTrue(uses_v2_orb_execution_profile("V2_ORB_PULLBACK"))
        self.assertTrue(uses_v2_orb_execution_profile(" v2_orb_pullback "))
        self.assertTrue(uses_v2_orb_execution_profile("V2_SPY_TREND_CONT"))
        self.assertTrue(uses_v2_orb_execution_profile("V2_SPY_AFTERNOON_FVG"))
        self.assertTrue(uses_v2_orb_execution_profile("V2_TSLA_TWO_LEG_TREND_PULLBACK"))

    def test_other_strategies_do_not_receive_v2_policy(self) -> None:
        self.assertFalse(uses_v2_orb_execution_profile("INST_ORB"))
        self.assertFalse(uses_v2_orb_execution_profile("V2_SPY_AFTERNOON_REVERSAL"))
        self.assertFalse(uses_v2_orb_execution_profile(None))


if __name__ == "__main__":
    unittest.main()

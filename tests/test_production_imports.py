"""Import smoke tests for modules loaded lazily by the live trading loop."""

import unittest


class ProductionImportTests(unittest.TestCase):
    def test_candidate_observation_imports_with_current_execution_profile(self) -> None:
        from trading.entry.candidate_observation import observe_candidate_contract

        self.assertTrue(callable(observe_candidate_contract))


if __name__ == "__main__":
    unittest.main()

"""Regression coverage for dependencies used by the shared Tradier GET helper."""

import unittest

import broker.tradier_core as tradier_core


class TradierCoreImportTests(unittest.TestCase):
    def test_shared_get_helper_has_requests_dependency(self):
        """The helper calls requests.get; keep this import with the split module."""
        self.assertTrue(callable(tradier_core.requests.get))


if __name__ == "__main__":
    unittest.main()

import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from ai_reasoning.episode_cache import (
    cached_review, complete_observation, episode_key, remember_review,
)


class AsyncObservationTests(unittest.TestCase):
    @patch("ai_reasoning.decision_support.review_entry")
    def test_async_observation_is_forced_non_enforcing(self, review_entry):
        from ai_reasoning.decision_support import observe_entry_async

        result = object()
        completed = []
        review_entry.return_value = result
        thread = observe_entry_async(
            on_complete=completed.append, ticker="TSLA", strategy_id="V2_ORB_PULLBACK",
        )
        thread.join(1)

        self.assertFalse(thread.is_alive())
        review_entry.assert_called_once_with(
            enforced=False, ticker="TSLA", strategy_id="V2_ORB_PULLBACK",
        )
        self.assertEqual(completed, [result])

    @patch("ai_reasoning.decision_support.review_entry", side_effect=RuntimeError("storage failed"))
    def test_async_observation_reports_none_after_unexpected_failure(self, _review_entry):
        from ai_reasoning.decision_support import observe_entry_async

        completed = []
        thread = observe_entry_async(on_complete=completed.append, ticker="SPY")
        thread.join(1)

        self.assertFalse(thread.is_alive())
        self.assertEqual(completed, [None])


class AiEpisodeCacheTests(unittest.TestCase):
    def test_repeated_detection_reuses_first_clean_review(self) -> None:
        start = datetime.fromisoformat("2026-08-13T10:00:00-04:00")
        cache = {}
        result = SimpleNamespace(action="veto", error=None)
        key = episode_key("tsla", "v2_orb_pullback", "bearish")
        remember_review(cache, key=key, observed_at=start, result=result)

        self.assertIs(result, cached_review(cache, key=key, observed_at=start + timedelta(minutes=10)))
        # The episode remains active because its last detection was at 10:10.
        self.assertIs(result, cached_review(cache, key=key, observed_at=start + timedelta(minutes=24)))

    def test_quiet_gap_starts_a_new_episode(self) -> None:
        start = datetime.fromisoformat("2026-08-13T10:00:00-04:00")
        cache = {}
        key = episode_key("SPY", "V2_SPY_TREND_CONT", "bearish")
        remember_review(cache, key=key, observed_at=start, result=SimpleNamespace(error=None))
        self.assertIsNone(cached_review(cache, key=key, observed_at=start + timedelta(minutes=16)))
        self.assertNotIn(key, cache)

    def test_failed_review_is_not_cached(self) -> None:
        cache = {}
        now = datetime.fromisoformat("2026-08-13T10:00:00-04:00")
        key = episode_key("TSLA", "V2_ORB_PULLBACK", "bullish")
        remember_review(cache, key=key, observed_at=now, result=SimpleNamespace(error="timeout"))
        self.assertIsNone(cached_review(cache, key=key, observed_at=now + timedelta(minutes=1)))

    def test_clean_async_result_replaces_only_its_own_marker(self) -> None:
        now = datetime.fromisoformat("2026-08-13T10:00:00-04:00")
        key = episode_key("TSLA", "V2_ORB_PULLBACK", "bullish")
        marker = SimpleNamespace(error=None)
        result = SimpleNamespace(action="veto", error=None)
        cache = {}
        remember_review(cache, key=key, observed_at=now, result=marker)

        self.assertTrue(complete_observation(cache, key=key, marker=marker, result=result))
        self.assertIs(result, cached_review(cache, key=key, observed_at=now))
        self.assertFalse(complete_observation(cache, key=key, marker=marker, result=SimpleNamespace(error=None)))

    def test_failed_async_result_removes_marker_for_retry(self) -> None:
        now = datetime.fromisoformat("2026-08-13T10:00:00-04:00")
        key = episode_key("SPY", "V2_SPY_TREND_CONT", "bearish")
        marker = SimpleNamespace(error=None)
        cache = {}
        remember_review(cache, key=key, observed_at=now, result=marker)

        self.assertTrue(complete_observation(cache, key=key, marker=marker, result=None))
        self.assertNotIn(key, cache)


if __name__ == "__main__":
    unittest.main()

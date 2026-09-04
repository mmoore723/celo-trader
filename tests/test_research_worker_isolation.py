"""Worker lifecycle, bounded work, copied context, mode/account isolation."""
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import patch

from auth.context import get_current_user_id, set_current_user
from config import get_db_path, get_settings, save_settings
from config.research_snapshot import research_settings_snapshot
from trading.loop.research_worker import ResearchWorker


class ResearchWorkerTests(unittest.TestCase):
    def setUp(self):
        previous = get_current_user_id()
        self.addCleanup(set_current_user, previous, previous, False)
        set_current_user("worker-a", "worker-a", False)

    def test_snapshot_is_copied_scoped_and_cannot_save(self):
        settings = {"paper_trading": True, "active_broker_account_id": "a-paper"}
        with TemporaryDirectory() as path, patch("config.paths._USER_DATA", Path(path)):
            save_settings({"paper_trading": False})
            with research_settings_snapshot("worker-a", settings):
                settings["paper_trading"] = False
                self.assertTrue(get_settings()["paper_trading"])
                self.assertEqual("trades_paper.db", get_db_path().name)
                with self.assertRaises(RuntimeError):
                    save_settings({"paper_trading": False})
                self.assertNotEqual("a-paper", get_settings("worker-b").get("active_broker_account_id"))
            self.assertFalse(get_settings()["paper_trading"])
            self.assertEqual("trades_live.db", get_db_path().name)

    def test_wrong_authenticated_user_cannot_start_worker(self):
        with self.assertRaises(ValueError):
            ResearchWorker("worker-b", Event())

    def test_two_users_have_distinct_contexts_and_state(self):
        records, workers, done = [], [], [Event(), Event()]
        try:
            with patch("trading.loop.research_worker.get_settings", return_value={}):
                for index, user in enumerate(("worker-a", "worker-b")):
                    set_current_user(user, user, False)
                    def run(readers, snapshot, state, stopped, index=index):
                        records.append((get_current_user_id(), state))
                        state["owner"] = get_current_user_id()
                        done[index].set()
                    worker = ResearchWorker(user, Event(), run, lambda: ())
                    workers.append(worker)
                    worker.submit({"settings": {}})
                self.assertTrue(all(event.wait(2) for event in done))
            self.assertEqual({"worker-a", "worker-b"}, {row[0] for row in records})
            self.assertIsNot(records[0][1], records[1][1])
        finally:
            for worker in workers:
                worker.close()

    def test_busy_worker_does_not_queue_stale_jobs_or_restart_on_cleared_stop(self):
        entered, release, parent = Event(), Event(), Event()
        calls = []
        def run(*args):
            calls.append(1)
            entered.set()
            release.wait(3)
        worker = None
        try:
            with patch("trading.loop.research_worker.get_settings", return_value={}):
                worker = ResearchWorker("worker-a", parent, run, lambda: ())
                self.assertTrue(worker.submit({"settings": {}}))
                self.assertTrue(entered.wait(2))
                for _ in range(100):
                    self.assertFalse(worker.submit({"settings": {}}))
                parent.set()
                worker.close()
                parent.clear()
                self.assertFalse(worker.submit({"settings": {}}))
        finally:
            release.set()
            if worker:
                worker.close()
        self.assertEqual([1], calls)

    def test_account_change_rejects_pending_old_snapshot(self):
        from unittest.mock import Mock
        runner = Mock()
        worker = None
        try:
            with patch("trading.loop.research_worker.get_settings", return_value={"paper_trading": False}):
                worker = ResearchWorker("worker-a", Event(), runner, lambda: ())
                worker.submit({"settings": {"paper_trading": True}})
                worker.close()
            runner.assert_not_called()
        finally:
            if worker:
                worker.close()

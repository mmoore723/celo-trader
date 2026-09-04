"""One bounded, account-scoped research worker; never an execution thread."""
from contextvars import copy_context
from copy import deepcopy
import logging
from threading import Event, Lock, Thread
import time

from auth.context import get_current_user_id
from config import get_settings
from config.research_snapshot import research_settings_snapshot

logger = logging.getLogger("celo_trader.research")
_workers = {}
_registry_lock = Lock()


def account_identity(settings):
    return (settings.get("active_broker_account_id"),
            bool(settings.get("paper_trading", True)), settings.get("broker_provider", "alpaca"))


class ResearchWorker:
    def __init__(self, user_id, parent_stop, runner=None, reader_factory=None):
        from broker import get_clients
        from trading.loop.research_pass import market_readers, run_research_pass
        if get_current_user_id() != user_id:
            raise ValueError("Research worker user does not match authenticated context")
        self.user_id = user_id
        self.parent_stop = parent_stop
        self.closed = Event()  # Never cleared on a subsequent bot restart.
        self.wake = Event()
        self.lock = Lock()
        self.pending = None
        self.busy = False
        self.runner = runner or run_research_pass
        self.reader_factory = reader_factory or (lambda: market_readers(*get_clients()))
        context = copy_context()
        self.thread = Thread(target=context.run, args=(self._run,), daemon=True,
                             name=f"research-{user_id}")
        self.thread.start()

    def stopped(self):
        return self.closed.is_set() or self.parent_stop.is_set()

    def submit(self, snapshot):
        with self.lock:
            if self.stopped() or self.busy or self.pending is not None:
                return False  # No growing queue, duplicate pass, or stale replay.
            self.pending = deepcopy(snapshot)
            self.wake.set()
            return True

    def close(self):
        self.closed.set()
        self.wake.set()
        self.thread.join(timeout=1)

    def _run(self):
        readers, identity, state = None, None, {}
        while not self.stopped():
            self.wake.wait(timeout=1)
            with self.lock:
                snapshot, self.pending = self.pending, None
                self.wake.clear()
                self.busy = snapshot is not None
            if snapshot is None:
                continue
            started = time.monotonic()
            try:
                settings = snapshot["settings"]
                target = account_identity(settings)
                # Check current account outside the pinned research context.
                if self.stopped() or account_identity(get_settings()) != target:
                    continue
                if identity != target:
                    readers, identity, state = self.reader_factory(), target, {}
                with research_settings_snapshot(self.user_id, settings):
                    self.runner(readers, snapshot, state, self.stopped)
            except Exception:
                logger.warning("Research worker failed; trading loop is independent", exc_info=True)
            finally:
                with self.lock:
                    self.busy = False
                logger.info("research_pass seconds=%.2f", time.monotonic() - started)


def submit_research(user_id, parent_stop, snapshot):
    with _registry_lock:
        worker = _workers.get(user_id)
        if worker is None or not worker.thread.is_alive():
            worker = _workers[user_id] = ResearchWorker(user_id, parent_stop)
        return worker.submit(snapshot)


def stop_research(user_id):
    with _registry_lock:
        worker = _workers.get(user_id)
        if worker is not None:
            worker.close()

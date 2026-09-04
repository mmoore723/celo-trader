"""Pin read-only research to the account/mode that started its work."""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy

_snapshot = ContextVar("research_settings_snapshot", default=None)


def current_snapshot(user_id):
    value = _snapshot.get()
    if value is not None and value[0] == user_id:
        return deepcopy(value[1])
    return None


@contextmanager
def research_settings_snapshot(user_id, settings):
    # This changes only this worker's reads, never the saved configuration.
    token = _snapshot.set((user_id, deepcopy(settings)))
    try:
        yield
    finally:
        _snapshot.reset(token)

"""Bound optional market reads on the single order-writing thread.

No order, cancellation or account request uses this budget. ContextVars keep
research and other users independent from an entry scan's deadline.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import time
import requests

_deadline = ContextVar('market_read_deadline', default=None)


@contextmanager
def market_read_budget(seconds):
    previous = _deadline.get()
    end = time.monotonic() + seconds
    token = _deadline.set(min(end, previous) if previous is not None else end)
    try:
        yield
    finally:
        _deadline.reset(token)


def entry_read_scope(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        token = _deadline.set(None)
        try:
            return function(*args, **kwargs)
        finally:
            _deadline.reset(token)
    return wrapped


def start_entry_read_budget(open_trades):
    if open_trades:
        _deadline.set(time.monotonic() + 5)


def request_policy(is_market_data):
    deadline = _deadline.get() if is_market_data else None
    if deadline is None:
        return 10, 3
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise requests.exceptions.Timeout('Entry market-data budget exhausted; resume position checks')
    return min(2, remaining), 1

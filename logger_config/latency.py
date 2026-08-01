"""
logger_config/latency.py — _LatencyTimer: context manager that measures and
logs elapsed time.

Split out of the old single logger_config.py (2026-08-01, file-size
cleanup); no logic changed, only relocated. Imported directly by
broker/alpaca_core.py and broker/tradier_core.py
(`from logger_config import _LatencyTimer`) — re-exported at the package
level in logger_config/__init__.py to keep those call sites unchanged.
"""

import logging
import time


class _LatencyTimer:
    """
    Context manager that measures elapsed time and logs it when the block exits.

    Usage in broker.py:
        with _LatencyTimer(logger, "alpaca_get_bars", ticker="SPY", timeframe="5Min"):
            resp = self._get(url, params)

    Emits a structured log line on exit:
        {"event": "alpaca_get_bars", "latency_ms": 142, "ticker": "SPY", ...}
    """

    def __init__(
        self,
        log: logging.Logger,
        event: str,
        level: int = logging.DEBUG,
        **context,
    ):
        self._log     = log
        self._event   = event
        self._level   = level
        self._context = context
        self._t0: float = 0.0

    def __enter__(self):
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        elapsed_ms = round((time.perf_counter() - self._t0) * 1000, 1)
        payload = {"event": self._event, "latency_ms": elapsed_ms, **self._context}
        if exc_type is not None:
            payload["error"] = str(exc_val)
            self._log.warning(self._event, extra=payload)
        else:
            self._log.log(self._level, self._event, extra=payload)
        return False   # never suppress exceptions

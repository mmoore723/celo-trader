"""
logger_config/redaction.py — secret-value patterns to redact from log output.

Split out of the old single logger_config.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.

We match the *values* loaded from the environment so they can never appear
in a log file even if accidentally interpolated into a message or an
exception traceback.

_SECRET_PATTERNS is reassigned (not mutated in place) by
_load_secret_patterns() below — logger_config/formatting.py's
_JsonFormatter reads it via a live dotted lookup on this module
(`logger_config.redaction._SECRET_PATTERNS`) rather than a
`from ... import _SECRET_PATTERNS` binding, so it always sees the
current value even though this list gets replaced wholesale (not
appended to) after the lazy first-call population.
"""

import re
import threading

_SECRET_PATTERNS: list[re.Pattern] = []
_PATTERN_LOCK = threading.RLock()


def register_secret_values(values) -> None:
    """Add runtime-loaded per-user secrets to the process redaction set."""
    candidates = {str(value) for value in values if value and len(str(value)) >= 8}
    if not candidates:
        return
    with _PATTERN_LOCK:
        existing = {pattern.pattern for pattern in _SECRET_PATTERNS}
        for value in candidates:
            escaped = re.escape(value)
            if escaped not in existing:
                _SECRET_PATTERNS.append(re.compile(escaped))
                existing.add(escaped)


def _load_secret_patterns() -> None:
    """
    Import the actual secret values from config and compile patterns that will
    match them in log output.  Called lazily on first handler install so that
    config is fully loaded before we read from it.
    """
    global _SECRET_PATTERNS
    try:
        from config import ALPACA_SECRET_KEY, TRADIER_API_KEY, ALPACA_API_KEY
        candidates = [ALPACA_SECRET_KEY, TRADIER_API_KEY, ALPACA_API_KEY]
        _SECRET_PATTERNS = []
        register_secret_values(candidates)
    except Exception:
        pass   # config not yet ready — no patterns this run

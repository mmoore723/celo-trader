"""
logger_config/setup.py — setup_logging(): the public entry point.

Split out of the old single logger_config.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""

import logging

from config import LOG_LEVEL

from logger_config.redaction import _load_secret_patterns
from logger_config.handlers import LOG_FILE, _make_rotating_handler, _make_console_handler

_configured = False   # guard against double-configuration


def setup_logging(level: int = LOG_LEVEL) -> logging.Logger:
    """
    Configure the root 'celo_trader' logger with:
      - JSON daily file handler → bot.log (14 compressed troubleshooting days)
      - Plain-text StreamHandler  → stdout   (dev-friendly)

    Call exactly once at application startup.  Safe to call multiple times
    (subsequent calls are no-ops thanks to the _configured guard).

    Returns the root 'celo_trader' logger.
    """
    global _configured
    if _configured:
        return logging.getLogger("celo_trader")

    _load_secret_patterns()

    root = logging.getLogger("celo_trader")
    root.setLevel(level)

    # Remove any handlers that basicConfig or a previous import might have added
    root.handlers.clear()
    root.propagate = False   # don't double-log to the Python root logger

    root.addHandler(_make_rotating_handler())
    root.addHandler(_make_console_handler())

    _configured = True
    root.info(
        "logging_initialised",
        extra={
            "event": "logging_initialised",
            "log_file": str(LOG_FILE),
            "rotation": "midnight",
            "backup_count": 14,
            "compression": "gzip",
            "level": logging.getLevelName(level),
        },
    )
    return root

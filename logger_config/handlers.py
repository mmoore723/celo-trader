"""
logger_config/handlers.py — log paths and handler factories.

Split out of the old single logger_config.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""

import gzip
import logging
import logging.handlers
import shutil
from pathlib import Path

from config import BASE_DIR

from logger_config.formatting import _JsonFormatter

# ── Paths ─────────────────────────────────────────────────────────────────────

LOG_DIR  = BASE_DIR / "log"
LOG_DIR.mkdir(exist_ok=True)   # create log/ on first import
LOG_FILE = LOG_DIR / "bot.log"


def _make_rotating_handler() -> logging.handlers.TimedRotatingFileHandler:
    """Rotate at midnight and keep 14 compressed troubleshooting days."""
    handler = logging.handlers.TimedRotatingFileHandler(
        filename    = str(LOG_FILE),
        when        = "midnight",   # new file each trading day
        backupCount = 14,
        encoding    = "utf-8",
        utc         = False,        # rotate in server local time
    )
    # Suffix: bot.log.2026-07-09
    handler.suffix = "%Y-%m-%d"
    handler.namer = lambda name: f"{name}.gz"
    handler.rotator = _gzip_rotated_log
    handler.setFormatter(_JsonFormatter())
    return handler


def _gzip_rotated_log(source: str, destination: str) -> None:
    """Compress a completed daily log before removing its plain-text copy."""
    with open(source, "rb") as source_file, gzip.open(destination, "wb", compresslevel=6) as archive:
        shutil.copyfileobj(source_file, archive)
    Path(source).unlink()


def _make_console_handler() -> logging.StreamHandler:
    """Human-readable console output — NOT JSON (easier to read during dev)."""
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    ))
    return handler

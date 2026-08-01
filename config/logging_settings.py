"""
config/logging_settings.py — Base log level/format constants.

Split out of the old single config.py (2026-08-01, file-size cleanup); no
logic changed, only relocated.
"""

import logging

LOG_LEVEL  = logging.INFO
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

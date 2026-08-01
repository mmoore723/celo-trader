"""
logger_config/formatting.py — _JsonFormatter: emits one JSON object per log
line, with secret redaction.

Split out of the old single logger_config.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""

import json
import logging

import logger_config.redaction as _redaction


class _JsonFormatter(logging.Formatter):
    """
    Emit one JSON object per log line.

    Mandatory fields (always present):
        timestamp   – ISO 8601 with milliseconds
        level       – WARNING, ERROR, etc.
        module_name – e.g. "celo_trader.broker"
        line_number – source line that emitted the record

    Optional fields (present when supplied via extra={}):
        Any key passed in extra={} is merged in at the top level.

    Secret redaction:
        After serialisation the raw JSON string is scanned against
        _SECRET_PATTERNS and matching substrings are replaced with
        "***REDACTED***".
    """

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        # Build the core payload
        payload: dict = {
            "timestamp":   self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S"),
            "level":       record.levelname,
            "module_name": record.name,
            "line_number": record.lineno,
            "message":     record.getMessage(),
        }

        # Milliseconds suffix
        payload["timestamp"] += f".{record.msecs:03.0f}Z"

        # Merge any extra fields the caller passed in extra={}
        # Skip internal LogRecord attributes to avoid noise
        _skip = {
            "name", "msg", "args", "created", "filename", "funcName",
            "levelname", "levelno", "lineno", "module", "msecs",
            "pathname", "process", "processName", "relativeCreated",
            "stack_info", "thread", "threadName", "exc_info", "exc_text",
            "message",
        }
        for key, value in record.__dict__.items():
            if key not in _skip and not key.startswith("_"):
                payload[key] = value

        # Exception info
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        # Serialise
        try:
            raw = json.dumps(payload, default=str)
        except Exception:
            raw = json.dumps({"timestamp": payload["timestamp"],
                              "level": record.levelname,
                              "message": repr(record.getMessage())})

        # Redact secrets — live dotted lookup, see redaction.py's module
        # docstring for why this isn't a `from ... import _SECRET_PATTERNS`.
        for pattern in _redaction._SECRET_PATTERNS:
            raw = pattern.sub("***REDACTED***", raw)

        return raw

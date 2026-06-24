"""
logger_config.py — Production-ready structured logging for CeloTrader.

Features:
  - JSON-formatted log lines (every field parseable by Splunk / any log aggregator)
  - Mandatory fields on every entry: timestamp, level, module_name, line_number
  - RotatingFileHandler: 10 MB max, 5 backup files
  - Secret redaction: ALPACA_SECRET_KEY and TRADIER_API_KEY values are masked
  - Decoupled from trade execution: a logging failure never raises to the caller
  - TradeContext adapter: bind ticker/contract/session_id once, auto-included thereafter

Usage
-----
    from logger_config import setup_logging, get_trade_logger

    # Call once at startup (main.py / dashboard.py entry point):
    setup_logging()

    # Normal per-module logger (unchanged pattern):
    logger = logging.getLogger("celo_trader.broker")

    # Trade-scoped logger that auto-attaches trade metadata to every line:
    tlog = get_trade_logger(ticker="SPY", contract_symbol="SPY240621C00530000", session_id="abc123")
    tlog.info("order_submitted", extra={"order_id": "xyz"})
"""

import json
import logging
import logging.handlers
import re
import time
from pathlib import Path
from typing import Optional

from config import BASE_DIR, LOG_LEVEL

# ── Paths ─────────────────────────────────────────────────────────────────────

LOG_DIR  = BASE_DIR / "log"
LOG_DIR.mkdir(exist_ok=True)   # create log/ on first import
LOG_FILE = LOG_DIR / "bot.log"

# ── Secret patterns to redact ─────────────────────────────────────────────────
# We match the *values* loaded from the environment so they can never appear
# in a log file even if accidentally interpolated into a message or an
# exception traceback.

_SECRET_PATTERNS: list[re.Pattern] = []


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
        _SECRET_PATTERNS = [
            re.compile(re.escape(v))
            for v in candidates
            if v and len(v) >= 8          # skip empty / placeholder strings
        ]
    except Exception:
        pass   # config not yet ready — no patterns this run


# ── JSON formatter ────────────────────────────────────────────────────────────

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

        # Redact secrets
        for pattern in _SECRET_PATTERNS:
            raw = pattern.sub("***REDACTED***", raw)

        return raw


# ── Latency context manager ───────────────────────────────────────────────────

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


# ── TradeContext LoggerAdapter ────────────────────────────────────────────────

class TradeContext(logging.LoggerAdapter):
    """
    Binds trade metadata to every log call without requiring the caller to pass
    it manually each time.

    Create once at the start of a trade:
        tlog = get_trade_logger(
            ticker="SPY",
            contract_symbol="SPY240621C00530000",
            session_id="abc-123",
        )

    Then log as normal — ticker/contract_symbol/session_id are auto-injected:
        tlog.info("order_submitted", extra={"order_id": "xyz"})
        tlog.error("fill_timeout", extra={"waited_secs": 30})

    Clear the context after the trade closes:
        tlog.clear_context()
    """

    def __init__(self, logger: logging.Logger, **context):
        super().__init__(logger, extra=context)
        self._context = context

    def process(self, msg, kwargs):
        extra = dict(self._context)
        extra.update(kwargs.get("extra", {}))
        kwargs["extra"] = extra
        return msg, kwargs

    def clear_context(self) -> None:
        """Call when the trade lifecycle ends so stale metadata isn't reused."""
        self._context.clear()
        self.extra = {}


def get_trade_logger(
    ticker: str,
    contract_symbol: str = "",
    session_id: str = "",
    base_name: str = "celo_trader.trading_logic",
) -> TradeContext:
    """
    Return a TradeContext adapter bound to the given trade identifiers.
    The underlying logger is the standard module logger so its level and
    handlers are inherited automatically.
    """
    return TradeContext(
        logging.getLogger(base_name),
        ticker=ticker,
        contract_symbol=contract_symbol,
        session_id=session_id,
    )


# ── Handler factory ───────────────────────────────────────────────────────────

def _make_rotating_handler() -> logging.handlers.RotatingFileHandler:
    """10 MB per file, keep 5 backups — bot.log never grows unbounded."""
    handler = logging.handlers.RotatingFileHandler(
        filename    = str(LOG_FILE),
        maxBytes    = 10 * 1024 * 1024,   # 10 MB
        backupCount = 5,
        encoding    = "utf-8",
    )
    handler.setFormatter(_JsonFormatter())
    return handler


def _make_console_handler() -> logging.StreamHandler:
    """Human-readable console output — NOT JSON (easier to read during dev)."""
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    ))
    return handler


# ── Public entry point ────────────────────────────────────────────────────────

_configured = False   # guard against double-configuration


def setup_logging(level: int = LOG_LEVEL) -> logging.Logger:
    """
    Configure the root 'celo_trader' logger with:
      - JSON RotatingFileHandler  → bot.log  (10 MB × 5 backups)
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
            "max_bytes": 10 * 1024 * 1024,
            "backup_count": 5,
            "level": logging.getLevelName(level),
        },
    )
    return root

"""
logger_config/__init__.py — Production-ready structured logging for CeloTrader.

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

Split (2026-08-01, file-size cleanup) out of the old single
logger_config.py into redaction.py, formatting.py, latency.py,
trade_context.py, handlers.py, and setup.py; no logic changed, only
relocated. A research pass before this split confirmed every external
consumer uses `from logger_config import X` (never a whole-module
`import logger_config as X` + dotted access), and that only
setup_logging, get_trade_logger, and _LatencyTimer cross module
boundaries — everything else (TradeContext, _JsonFormatter,
_SECRET_PATTERNS, _load_secret_patterns, _configured, LOG_DIR, LOG_FILE,
_make_rotating_handler, _make_console_handler) is internal-only. No
external A/B-test-style monkey-patching was found for this module (unlike
strategies/vwap_pb.py and strategy_router.py earlier in this refactor
pass), so this __init__.py's re-exports are plain convenience imports —
no live-dotted-lookup tricks needed for setup_logging/get_trade_logger/
_LatencyTimer/TradeContext.

NOTE on _SECRET_PATTERNS specifically: it is NOT re-exported here by value.
_load_secret_patterns() REASSIGNS (not mutates in place) the list in
redaction.py's own namespace — a `from logger_config.redaction import
_SECRET_PATTERNS` copy captured here at package-import time (before
setup_logging() has run) would go stale the moment _load_secret_patterns()
replaces the list, exactly like the vwap_pb.py/strategy_router.py
monkey-patch hazard elsewhere in this refactor, just triggered internally
instead of by an external A/B script. formatting.py's _JsonFormatter reads
it correctly via a live dotted lookup on the redaction module
(`logger_config.redaction._SECRET_PATTERNS`) — anyone else needing the
live value should do the same rather than `logger_config._SECRET_PATTERNS`.
_load_secret_patterns itself IS safe to re-export (it's a function).
"""

from logger_config.redaction import _load_secret_patterns
from logger_config.formatting import _JsonFormatter
from logger_config.latency import _LatencyTimer
from logger_config.trade_context import TradeContext, get_trade_logger
from logger_config.handlers import (
    LOG_DIR,
    LOG_FILE,
    _make_rotating_handler,
    _make_console_handler,
)
from logger_config.setup import setup_logging

__all__ = [
    "_load_secret_patterns",
    "_JsonFormatter",
    "_LatencyTimer",
    "TradeContext",
    "get_trade_logger",
    "LOG_DIR",
    "LOG_FILE",
    "_make_rotating_handler",
    "_make_console_handler",
    "setup_logging",
]

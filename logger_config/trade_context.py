"""
logger_config/trade_context.py — TradeContext adapter + get_trade_logger().

Split out of the old single logger_config.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""

import logging


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
